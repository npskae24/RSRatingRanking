"""
Equity simulation with the FULL PART III technical scoring (6 weighted columns,
per the real SCORING SYSTEM V1.0.xlsx table reproduced in the V4.2 addendum SS1)
plus a PART I RS score, replacing the 3-criterion AND-filter used in
simulate_equity_curve_2020_2026.py. Same panel, sizing, and exit rule as that
baseline so this isolates the "does full weighted scoring beat a simple filter"
question.

PART II Base Quality (30 pts: Prior Uptrend, Base Depth, Last T, VDU, Shakeout,
52WH/ATH Distance, MA10/20 Support) is NOT included - none of those criteria are
computed anywhere in the pipeline (they're chart-reading criteria never coded),
so they can't be backtested without designing new formulas first (a separate,
larger task). This means the ACE>=75/100 bar can't be applied literally either -
see COMPUTABLE_MAX and PASS_THRESHOLD below for how this version handles that gap.

Scoring implemented (all from pipeline-computable columns):
  PART I  - RS Score        0-40 pts = rs_rank * 40
          - Breakout Area   0-10 pts = BreakoutVolumeConfirmed ? 10 : 0
  PART III (20 pts total, buckets per addendum SS1 table):
          - row12 BreakoutVolumeConfirmed  0/4
          - row13 VolumeRatio              tiered 0/2.2/2.8/3.4/4
          - row14 TightBase                0/4
          - row15 HighToClose_252d         tiered 0/1.6/2.8/4
          - row16 SectorRS                 tiered 0/0.8/1.4/2
          - row17 AvgValue_20d             tiered 0/0.8/1.4/2 (liquidity cutoffs
                                            are MY OWN assumption - addendum says
                                            re-base to your own comfort level,
                                            no source cutoffs exist for traded value)
COMPUTABLE_MAX = 50 (PART I) + 20 (PART III) = 70. Real ACE bar is score/100 >= 0.75;
applied here as score/70 >= 0.75 (PASS_THRESHOLD = 52.5) - this implicitly assumes
the missing PART II would score at its own 75th-percentile-equivalent on average,
which is optimistic, not a validated substitute. Flag this every time this script's
numbers are quoted.
"""
import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(__file__)
REPO_ROOT = os.path.dirname(HERE)
PRICE_CACHE = os.path.join(HERE, "price_cache_2018_2026.csv")
VOLUME_CACHE = os.path.join(HERE, "volume_cache_2018_2026.csv")
SECTOR_HTML = os.path.join(REPO_ROOT, "set_stock_list", "listedCompanies_en_US.html")
TRADE_LOG_CSV = os.path.join(HERE, "equity_sim_trades_fullscore_2020_2026.csv")
EQUITY_CSV = os.path.join(HERE, "equity_sim_curve_fullscore_2020_2026.csv")

PERIODS = [63, 126, 189, 252]
WEIGHTS = [0.4, 0.2, 0.2, 0.2]
RANKING_THRESHOLD = 0.8  # watchlist pre-filter (top 20% RS), same as production

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

COMPUTABLE_MAX = 70.0
PASS_THRESHOLD = 0.75 * COMPUTABLE_MAX  # 52.5

# Liquidity tiers for AvgValue_20d (20-day avg traded value, THB) - MY assumption,
# addendum explicitly has no source cutoffs for this (only old market-cap tiers
# which aren't the same scale as traded value).
LIQUIDITY_TIERS_THB = [20_000_000, 50_000_000, 100_000_000]  # ascending: >=20M / >=50M / >=100M / else

SIM_START = pd.Timestamp("2020-01-02")
SIM_END = pd.Timestamp("2026-06-30")
STARTING_CAPITAL = 100_000.0


def load_panel():
    close = pd.read_csv(PRICE_CACHE, index_col=0, parse_dates=True).sort_index()
    vol = pd.read_csv(VOLUME_CACHE, index_col=0, parse_dates=True).sort_index()
    close, vol = close.align(vol, join="inner")
    return close, vol


def load_sector_map(columns):
    t = pd.read_html(SECTOR_HTML, header=1)[0]
    sr = t.set_index("Symbol")["Sector"].astype(str)
    bare = [c.split(".")[0] for c in columns]
    sr = sr.reindex(bare)
    sr.index = columns
    return sr.replace("-", np.nan)


def compute_rs_rank(close):
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
    return df_rs.rank(axis=1, pct=True)


def bucket_score_higher_better(value_df, thresholds_asc, points_asc, below_points):
    """thresholds_asc/points_asc: parallel, ascending. value >= thresholds_asc[i] -> points_asc[i]
    (highest threshold that's met wins). value below all thresholds -> below_points. NaN -> NaN
    (caller decides how to treat missing data, typically fillna(0) at sum time)."""
    arr = value_df.values
    conds = [arr >= t for t in thresholds_asc]
    out = np.select(list(reversed(conds)), list(reversed(points_asc)), default=below_points)
    return pd.DataFrame(out, index=value_df.index, columns=value_df.columns).where(value_df.notna())


def bucket_score_lower_better(value_df, thresholds_asc, points_desc, above_points):
    """thresholds_asc/points_desc: parallel, ascending thresholds with descending points
    (value <= thresholds_asc[i] -> points_desc[i], tightest/best threshold wins).
    value above all thresholds -> above_points. NaN -> NaN."""
    arr = value_df.values
    conds = [arr <= t for t in thresholds_asc]
    out = np.select(conds, points_desc, default=above_points)
    return pd.DataFrame(out, index=value_df.index, columns=value_df.columns).where(value_df.notna())


def compute_signals(close, vol):
    rs_rank = compute_rs_rank(close)

    high_n = close.rolling(BASE_LOOKBACK).max()
    low_n = close.rolling(BASE_LOOKBACK).min()
    tight_base = ((high_n - low_n) / low_n) <= BASE_TIGHTNESS_MAX
    tight_base_prev = tight_base.shift(1)

    prior_high = close.shift(1).rolling(BREAKOUT_LOOKBACK).max()
    vol_ratio = vol / vol.rolling(VOLUME_AVG_WINDOW).mean()
    breakout_with_volume = (close > prior_high) & (vol_ratio >= BREAKOUT_VOLUME_MULT)

    high_to_close_252d = close.rolling(252).max() / close - 1.0
    avg_value_20d = (close * vol).rolling(20).mean()

    sector_map = load_sector_map(close.columns)
    sector_rs = rs_rank.T.groupby(sector_map).mean().T  # date x sector
    sector_rs_per_stock = pd.DataFrame(
        {s: sector_rs[sector_map[s]] if pd.notna(sector_map[s]) and sector_map[s] in sector_rs.columns
         else pd.Series(np.nan, index=rs_rank.index)
         for s in close.columns}
    )

    market_index = (1 + close.pct_change(fill_method=None).mean(axis=1).fillna(0)).cumprod()
    regime_up = market_index > market_index.rolling(MARKET_TREND_WINDOW).mean()
    ma_trail = close.rolling(TRAIL_MA_WINDOW).mean()

    # --- PART I ---
    rs_score = rs_rank * 40.0
    breakout_area = breakout_with_volume.astype(float) * 10.0

    # --- PART III ---
    row12 = breakout_with_volume.astype(float) * 4.0
    row13 = bucket_score_higher_better(vol_ratio, [1.0, 1.5, 2.0, 3.0], [2.2, 2.8, 3.4, 4.0], below_points=1.2)
    row14 = tight_base.astype(float) * 4.0
    row15 = bucket_score_lower_better(high_to_close_252d, [0.05, 0.15, 0.30], [4.0, 2.8, 1.6], above_points=0.0)
    row16 = bucket_score_higher_better(sector_rs_per_stock, [0.4, 0.6, 0.8], [0.8, 1.4, 2.0], below_points=0.0)
    row17 = bucket_score_higher_better(avg_value_20d, LIQUIDITY_TIERS_THB, [0.8, 1.4, 2.0], below_points=0.0)

    # missing technical data (rolling-window warmup, unclassified sector, etc.) scores 0
    # on that row rather than blocking the whole candidate.
    total_score = (rs_score.fillna(0) + breakout_area.fillna(0)
                   + row12.fillna(0) + row13.fillna(0) + row14.fillna(0)
                   + row15.fillna(0) + row16.fillna(0) + row17.fillna(0))
    entry_signal = (rs_rank >= RANKING_THRESHOLD) & (total_score >= PASS_THRESHOLD)

    return rs_rank, total_score, entry_signal, regime_up, ma_trail


def simulate(close, rs_rank, total_score, entry_signal, regime_up, ma_trail):
    dates = close.index[(close.index >= SIM_START) & (close.index <= SIM_END)]
    cash = STARTING_CAPITAL
    positions = {}
    equity_curve = []
    trade_log = []

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
                cand_score = total_score.loc[d, candidates].sort_values(ascending=False)
                chosen = cand_score.index[:slots]
                size_mult = 1.0 if bool(regime_up.loc[d]) else REGIME_DOWN_SIZE_MULT
                for sym in chosen:
                    p = px.get(sym, np.nan)
                    if pd.isna(p) or p <= 0:
                        continue
                    alloc = min(equity * POSITION_SIZE_PCT * size_mult, cash)
                    if alloc <= 0:
                        continue
                    shares = alloc / p
                    cash -= alloc
                    positions[sym] = {"shares": shares, "entry_price": p, "entry_date": d}

        held_value = sum(positions[s]["shares"] * px.get(s, positions[s]["entry_price"]) for s in positions)
        equity = cash + held_value
        equity_curve.append((d, equity, cash, len(positions)))

    equity_df = pd.DataFrame(equity_curve, columns=["date", "equity", "cash", "n_positions"]).set_index("date")
    trade_df = pd.DataFrame(trade_log)
    return equity_df, trade_df


def max_drawdown(equity_sr):
    running_max = equity_sr.cummax()
    return (equity_sr / running_max - 1).min()


def cagr(equity_sr):
    n_years = (equity_sr.index[-1] - equity_sr.index[0]).days / 365.25
    return (equity_sr.iloc[-1] / equity_sr.iloc[0]) ** (1 / n_years) - 1


def main():
    close, vol = load_panel()
    print(f"Panel: {close.shape}, {close.index.min()} to {close.index.max()}")

    rs_rank, total_score, entry_signal, regime_up, ma_trail = compute_signals(close, vol)
    print(f"Signal days with >=1 candidate: {(entry_signal.sum(axis=1) > 0).sum()} / {len(entry_signal)}")

    equity_df, trade_df = simulate(close, rs_rank, total_score, entry_signal, regime_up, ma_trail)
    equity_df.to_csv(EQUITY_CSV)
    trade_df.to_csv(TRADE_LOG_CSV, index=False)

    print(f"\n=== Full PART I+III scoring (>=52.5/70), trailing-MA50/-8%stop exit ===")
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

    print(f"\nSaved equity curve to {EQUITY_CSV}, trade log to {TRADE_LOG_CSV}")


if __name__ == "__main__":
    main()
