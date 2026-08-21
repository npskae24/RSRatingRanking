"""
Same simulation as simulate_equity_curve_2020_2026.py (same panel, entry signal,
trailing-MA50/-8%-stop exit, 2020-01-02 to 2026-06-30, 100,000 THB start), plus
the addendum's SS4 discipline rules wired in as an actual throttle instead of a
documented-but-untested intention:

- MDD>15% rule: once equity drawdown from its running peak exceeds 15%, cut
  POSITION_SIZE_PCT from 5% to 3% (one further notch below the existing
  regime-down 3.75%) AND stop opening new positions entirely until equity
  recovers to within 5% of the prior peak (the "mandatory review before
  resuming normal sizing" made concrete: normal sizing/entries only resume
  once equity round-trips back near its old high).
- 5-consecutive-losses rule: after 5 closing trades in a row are losses,
  stop opening new positions until the next winning trade closes. Existing
  open positions keep running under their own exit rule regardless.

Everything else (RANKING_THRESHOLD, BASE_LOOKBACK, exit rule, etc.) is
identical to simulate_equity_curve_2020_2026.py for an apples-to-apples
comparison - only the sizing/entry-gating logic inside simulate() changed.
"""
import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(__file__)
PRICE_CACHE = os.path.join(HERE, "price_cache_2018_2026.csv")
VOLUME_CACHE = os.path.join(HERE, "volume_cache_2018_2026.csv")
TRADE_LOG_CSV = os.path.join(HERE, "equity_sim_trades_mdd_2020_2026.csv")
EQUITY_CSV = os.path.join(HERE, "equity_sim_curve_mdd_2020_2026.csv")

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

# SS4 discipline rules
MDD_THROTTLE_TRIGGER = 0.15   # drawdown from peak that triggers the throttle
MDD_THROTTLE_SIZE_PCT = 0.03  # sizing floor while throttled (below the 3.75% regime-down tier)
MDD_RECOVERY_BAND = 0.05      # throttle lifts once equity is back within 5% of prior peak
LOSING_STREAK_TRIGGER = 5     # consecutive losing closes that halts new entries

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

    peak_equity = STARTING_CAPITAL
    mdd_throttled = False
    consecutive_losses = 0
    loss_streak_halt = False

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
                cash += shares * p
                ret_pct = p / entry_price - 1
                trade_log.append({
                    "symbol": sym,
                    "entry_date": positions[sym]["entry_date"], "exit_date": d,
                    "entry_price": entry_price, "exit_price": p,
                    "return_pct": ret_pct,
                    "reason": "hard_stop" if hard_stop_hit else "trail_ma50",
                })
                del positions[sym]

                if ret_pct <= 0:
                    consecutive_losses += 1
                else:
                    consecutive_losses = 0
                    loss_streak_halt = False
                if consecutive_losses >= LOSING_STREAK_TRIGGER:
                    loss_streak_halt = True

        held_value = sum(positions[s]["shares"] * px.get(s, positions[s]["entry_price"]) for s in positions)
        equity = cash + held_value

        peak_equity = max(peak_equity, equity)
        current_dd = equity / peak_equity - 1
        if not mdd_throttled and current_dd <= -MDD_THROTTLE_TRIGGER:
            mdd_throttled = True
        elif mdd_throttled and equity >= peak_equity * (1 - MDD_RECOVERY_BAND):
            mdd_throttled = False

        slots = MAX_POSITIONS - len(positions)
        if slots > 0 and not mdd_throttled and not loss_streak_halt:
            todays_signal = entry_signal.loc[d]
            candidates = todays_signal[todays_signal].index.difference(list(positions.keys()))
            if len(candidates) > 0:
                cand_rs = rs_rank.loc[d, candidates].sort_values(ascending=False)
                chosen = cand_rs.index[:slots]
                size_pct = MDD_THROTTLE_SIZE_PCT if mdd_throttled else POSITION_SIZE_PCT
                size_mult = 1.0 if bool(regime_up.loc[d]) else REGIME_DOWN_SIZE_MULT
                for sym in chosen:
                    p = px.get(sym, np.nan)
                    if pd.isna(p) or p <= 0:
                        continue
                    alloc = min(equity * size_pct * size_mult, cash)
                    if alloc <= 0:
                        continue
                    shares = alloc / p
                    cash -= alloc
                    positions[sym] = {"shares": shares, "entry_price": p, "entry_date": d}

        held_value = sum(positions[s]["shares"] * px.get(s, positions[s]["entry_price"]) for s in positions)
        equity = cash + held_value
        equity_curve.append((d, equity, cash, len(positions), mdd_throttled, loss_streak_halt))

    equity_df = pd.DataFrame(
        equity_curve,
        columns=["date", "equity", "cash", "n_positions", "mdd_throttled", "loss_streak_halt"],
    ).set_index("date")
    trade_df = pd.DataFrame(trade_log)
    return equity_df, trade_df


def max_drawdown(equity_sr):
    running_max = equity_sr.cummax()
    dd = equity_sr / running_max - 1
    return dd.min()


def cagr(equity_sr):
    n_years = (equity_sr.index[-1] - equity_sr.index[0]).days / 365.25
    return (equity_sr.iloc[-1] / equity_sr.iloc[0]) ** (1 / n_years) - 1


def main():
    close, vol = load_panel()
    print(f"Panel: {close.shape}, {close.index.min()} to {close.index.max()}")

    rs_rank, entry_signal, regime_up, ma_trail, market_index = compute_signals(close, vol)
    equity_df, trade_df = simulate(close, rs_rank, entry_signal, regime_up, ma_trail)

    bench_sr = market_index.loc[equity_df.index]
    bench_sr = bench_sr / bench_sr.iloc[0] * STARTING_CAPITAL

    equity_df.to_csv(EQUITY_CSV)
    trade_df.to_csv(TRADE_LOG_CSV, index=False)

    print(f"\n=== Strategy + MDD>15% sizing throttle + 5-loss-streak halt ===")
    print(f"Start: {STARTING_CAPITAL:,.0f} THB on {equity_df.index[0].date()}")
    print(f"End:   {equity_df['equity'].iloc[-1]:,.0f} THB on {equity_df.index[-1].date()}")
    print(f"CAGR:  {cagr(equity_df['equity'])*100:.2f}%")
    print(f"Max drawdown: {max_drawdown(equity_df['equity'])*100:.2f}%")
    print(f"Total trades: {len(trade_df)}")
    if len(trade_df):
        wins = trade_df[trade_df['return_pct'] > 0]
        losses = trade_df[trade_df['return_pct'] <= 0]
        print(f"Win rate: {len(wins)/len(trade_df)*100:.1f}%")
        print(f"Avg gain: {wins['return_pct'].mean()*100:.2f}%  Avg loss: {losses['return_pct'].mean()*100:.2f}%")
        print(f"Exit reason counts:\n{trade_df['reason'].value_counts()}")
    print(f"Days MDD-throttled: {equity_df['mdd_throttled'].sum()} / {len(equity_df)}")
    print(f"Days loss-streak-halted: {equity_df['loss_streak_halt'].sum()} / {len(equity_df)}")

    print(f"\n=== Benchmark: equal-weight SET proxy, buy & hold ===")
    print(f"Start: {STARTING_CAPITAL:,.0f} THB on {bench_sr.index[0].date()}")
    print(f"End:   {bench_sr.iloc[-1]:,.0f} THB on {bench_sr.index[-1].date()}")
    print(f"CAGR:  {cagr(bench_sr)*100:.2f}%")
    print(f"Max drawdown: {max_drawdown(bench_sr)*100:.2f}%")

    print(f"\nSaved equity curve to {EQUITY_CSV}, trade log to {TRADE_LOG_CSV}")


if __name__ == "__main__":
    main()
