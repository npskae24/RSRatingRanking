"""
Same simulation as simulate_equity_curve_2020_2026.py (see that file's docstring
for the full rules), with one addition: realistic Thai retail brokerage
transaction costs deducted on every buy and every sell, to see how much they eat
into the reported edge (win rate was only 25.6% in the no-cost run, so this
strategy is cost-sensitive).

Cost model (ROUNDTRIP_COST_PCT_PER_SIDE, applied once per side, i.e. twice per
round-trip trade):
- Brokerage commission ~0.15% (typical Thai online retail rate - an assumption,
  not a confirmed rate from any specific broker; real rates range roughly
  0.10-0.25% depending on broker/volume tier)
- SET trading fee ~0.005% + clearing fee ~0.001%
- 7% VAT on the commission portion only (0.15% * 0.07 = 0.0105%)
Total ~= 0.15 + 0.005 + 0.001 + 0.0105 = 0.1665% per side.
"""
import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(__file__)
PRICE_CACHE = os.path.join(HERE, "price_cache_2018_2026.csv")
VOLUME_CACHE = os.path.join(HERE, "volume_cache_2018_2026.csv")
TRADE_LOG_CSV = os.path.join(HERE, "equity_sim_trades_txncost_2020_2026.csv")
EQUITY_CSV = os.path.join(HERE, "equity_sim_curve_txncost_2020_2026.csv")

PERIODS = [63, 126, 189, 252]
WEIGHTS = [0.4, 0.2, 0.2, 0.2]
RANKING_THRESHOLD = 0.8

BASE_LOOKBACK = 20
BASE_TIGHTNESS_MAX = 0.15
BREAKOUT_LOOKBACK = 20
VOLUME_AVG_WINDOW = 50
BREAKOUT_VOLUME_MULT = 1.5
MARKET_TREND_WINDOW = 50

TRAIL_MA_WINDOW = 50
HARD_STOP_PCT = 0.08
POSITION_SIZE_PCT = 0.05
REGIME_DOWN_SIZE_MULT = 0.75
MAX_POSITIONS = 20

ROUNDTRIP_COST_PCT_PER_SIDE = 0.001665  # commission + SET fees + VAT, see module docstring

SIM_START = pd.Timestamp("2020-01-02")
SIM_END = pd.Timestamp("2026-06-30")
STARTING_CAPITAL = 100_000.0


def load_panel():
    close = pd.read_csv(PRICE_CACHE, index_col=0, parse_dates=True).sort_index()
    vol = pd.read_csv(VOLUME_CACHE, index_col=0, parse_dates=True).sort_index()
    close, vol = close.align(vol, join="inner")
    return close, vol


def compute_signals(close, vol):
    df_returns = pd.DataFrame(
        index=close.index,
        columns=pd.MultiIndex.from_product([close.columns, PERIODS], names=["SecCode", "Period"]),
        dtype=float,
    )
    for p in PERIODS:
        shifted = close.shift(p)
        df_returns.loc[:, (slice(None), p)] = ((close - shifted) / shifted).values
    weights_s = pd.Series(WEIGHTS, index=PERIODS)
    df_rs = (
        df_returns.stack(level=0, future_stack=True)
        .mul(weights_s, axis=1)
        .sum(axis=1, min_count=1)
        .unstack(level=1)
    )
    rs_rank = df_rs.rank(axis=1, pct=True)

    high_n = close.rolling(BASE_LOOKBACK).max()
    low_n = close.rolling(BASE_LOOKBACK).min()
    tight_base = ((high_n - low_n) / low_n) <= BASE_TIGHTNESS_MAX
    prior_high = close.shift(1).rolling(BREAKOUT_LOOKBACK).max()
    vol_ratio = vol / vol.rolling(VOLUME_AVG_WINDOW).mean()
    breakout_with_volume = (close > prior_high) & (vol_ratio >= BREAKOUT_VOLUME_MULT)
    entry_signal = tight_base.shift(1) & breakout_with_volume & (rs_rank >= RANKING_THRESHOLD)

    market_index = (1 + close.pct_change(fill_method=None).mean(axis=1).fillna(0)).cumprod()
    regime_up = market_index > market_index.rolling(MARKET_TREND_WINDOW).mean()

    ma_trail = close.rolling(TRAIL_MA_WINDOW).mean()

    return rs_rank, entry_signal, regime_up, ma_trail, market_index


def simulate(close, rs_rank, entry_signal, regime_up, ma_trail):
    dates = close.index[(close.index >= SIM_START) & (close.index <= SIM_END)]
    cash = STARTING_CAPITAL
    positions = {}
    equity_curve = []
    trade_log = []
    total_cost_thb = 0.0

    for d in dates:
        px = close.loc[d]

        for sym in list(positions.keys()):
            p = px.get(sym, np.nan)
            if pd.isna(p):
                continue
            entry_price = positions[sym]["entry_price"]
            ma = ma_trail.at[d, sym] if sym in ma_trail.columns else np.nan
            hard_stop_hit = (p / entry_price - 1) <= -HARD_STOP_PCT
            trail_hit = (not pd.isna(ma)) and (p < ma)
            if hard_stop_hit or trail_hit:
                shares = positions[sym]["shares"]
                proceeds = shares * p
                cost = proceeds * ROUNDTRIP_COST_PCT_PER_SIDE
                cash += proceeds - cost
                total_cost_thb += cost
                trade_log.append({
                    "symbol": sym,
                    "entry_date": positions[sym]["entry_date"], "exit_date": d,
                    "entry_price": entry_price, "exit_price": p,
                    "return_pct": p / entry_price - 1,
                    "reason": "hard_stop" if hard_stop_hit else "trail_ma50",
                })
                del positions[sym]

        held_value = sum(positions[s]["shares"] * px.get(s, positions[s]["entry_price"]) for s in positions)
        equity = cash + held_value

        slots = MAX_POSITIONS - len(positions)
        if slots > 0:
            todays_signal = entry_signal.loc[d]
            candidates = todays_signal[todays_signal].index.difference(list(positions.keys()))
            if len(candidates) > 0:
                cand_rs = rs_rank.loc[d, candidates].sort_values(ascending=False)
                chosen = cand_rs.index[:slots]
                size_mult = 1.0 if bool(regime_up.loc[d]) else REGIME_DOWN_SIZE_MULT
                for sym in chosen:
                    p = px.get(sym, np.nan)
                    if pd.isna(p) or p <= 0:
                        continue
                    alloc = min(equity * POSITION_SIZE_PCT * size_mult, cash)
                    if alloc <= 0:
                        continue
                    cost = alloc * ROUNDTRIP_COST_PCT_PER_SIDE
                    if alloc + cost > cash:
                        alloc = cash / (1 + ROUNDTRIP_COST_PCT_PER_SIDE)
                        cost = alloc * ROUNDTRIP_COST_PCT_PER_SIDE
                    shares = alloc / p
                    cash -= alloc + cost
                    total_cost_thb += cost
                    positions[sym] = {"shares": shares, "entry_price": p, "entry_date": d}

        held_value = sum(positions[s]["shares"] * px.get(s, positions[s]["entry_price"]) for s in positions)
        equity = cash + held_value
        equity_curve.append((d, equity, cash, len(positions)))

    equity_df = pd.DataFrame(equity_curve, columns=["date", "equity", "cash", "n_positions"]).set_index("date")
    trade_df = pd.DataFrame(trade_log)
    return equity_df, trade_df, total_cost_thb


def max_drawdown(equity_sr):
    running_max = equity_sr.cummax()
    dd = equity_sr / running_max - 1
    return dd.min()


def cagr(equity_sr):
    n_years = (equity_sr.index[-1] - equity_sr.index[0]).days / 365.25
    return (equity_sr.iloc[-1] / equity_sr.iloc[0]) ** (1 / n_years) - 1


# No-cost baseline already on record (simulate_equity_curve_2020_2026.py), for direct comparison.
BASELINE_FINAL_EQUITY = 234_365.0
BASELINE_CAGR = 0.1402
BASELINE_MAX_DD = -0.471
BASELINE_TRADES = 1098
BENCHMARK_CAGR = 0.1044


def main():
    close, vol = load_panel()
    print(f"Panel: {close.shape}, {close.index.min()} to {close.index.max()}")

    rs_rank, entry_signal, regime_up, ma_trail, market_index = compute_signals(close, vol)
    equity_df, trade_df, total_cost_thb = simulate(close, rs_rank, entry_signal, regime_up, ma_trail)

    equity_df.to_csv(EQUITY_CSV)
    trade_df.to_csv(TRADE_LOG_CSV, index=False)

    final_equity = equity_df['equity'].iloc[-1]
    strat_cagr = cagr(equity_df['equity'])
    strat_mdd = max_drawdown(equity_df['equity'])

    print(f"\n=== Strategy WITH transaction costs ({ROUNDTRIP_COST_PCT_PER_SIDE*100:.4f}% per side) ===")
    print(f"Start: {STARTING_CAPITAL:,.0f} THB on {equity_df.index[0].date()}")
    print(f"End:   {final_equity:,.0f} THB on {equity_df.index[-1].date()}")
    print(f"CAGR:  {strat_cagr*100:.2f}%")
    print(f"Max drawdown: {strat_mdd*100:.2f}%")
    print(f"Total trades: {len(trade_df)}")
    print(f"Total transaction cost paid: {total_cost_thb:,.0f} THB")
    if len(trade_df):
        wins = trade_df[trade_df['return_pct'] > 0]
        print(f"Win rate: {len(wins)/len(trade_df)*100:.1f}%")

    print(f"\n=== Comparison vs no-cost baseline (simulate_equity_curve_2020_2026.py) ===")
    print(f"Final equity: {final_equity:,.0f} THB  vs  {BASELINE_FINAL_EQUITY:,.0f} THB no-cost "
          f"(-{BASELINE_FINAL_EQUITY - final_equity:,.0f} THB, {(final_equity/BASELINE_FINAL_EQUITY - 1)*100:.2f}%)")
    print(f"CAGR: {strat_cagr*100:.2f}%  vs  {BASELINE_CAGR*100:.2f}% no-cost "
          f"(-{(BASELINE_CAGR - strat_cagr)*100:.2f}pp drag)")
    print(f"Benchmark CAGR (equal-weight SET, buy&hold, no cost modeled): {BENCHMARK_CAGR*100:.2f}%")
    print(f"Edge over benchmark after costs: {(strat_cagr - BENCHMARK_CAGR)*100:.2f}pp "
          f"(no-cost edge was {(BASELINE_CAGR - BENCHMARK_CAGR)*100:.2f}pp)")

    print(f"\nSaved equity curve to {EQUITY_CSV}, trade log to {TRADE_LOG_CSV}")


if __name__ == "__main__":
    main()
