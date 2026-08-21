"""
Equity simulation with the LITERAL scoring formula reverse-engineered from the real
`SCORING SYSTEM V1.2 (PART III technical swap, 2026-08-20).xlsx` (openpyxl formula
read, not just the displayed SCORING TABLE legend - which turned out stale/wrong in
two places, see notes below). This is the closest approximation yet of the full
ACE>=75/100 rule - PART I RS (50) + PART II Base Quality (30) + PART III Technical
(20), replacing simulate_full_scoring_2020_2026.py's 70-point PART I+III-only proxy.

Formula provenance: SCORING SYSTEM sheet's Score column cells are nested IF formulas
referencing PARAMETER sheet cells (e.g. `=IF(C8>=PARAMETER!D3,PARAMETER!E3,...)`).
Read those formulas directly via openpyxl(data_only=False) and cross-checked against
the sheet's own worked example (SNNP, C column inputs -> D column scores) - the
SCORING TABLE sheet's displayed bucket text turned out STALE/WRONG for two rows
(PRIOR UPTREND, BASE LENGTH) relative to the live formula; PARAMETER's own raw
numbers were trusted instead, verified against the worked example.

Two REAL BUGS found in the live spreadsheet formula (replicated here faithfully,
not "fixed", since the goal is to test the process as it actually runs today):
  - BASE DEPTH: the >=30%-depth branch (meant to score 1.8, worse than the 10-25%
    peak of 6) is unreachable dead code - the preceding >=25% check already catches
    it and returns 3 first. Real behavropr: <10%->3, [10%,25%)->6 (peak), >=25%->3
    (flat, the >=30% tier for "too deep" never actually fires).
  - PRIOR UPTREND: the >=50% and >=25% tiers both score 3.6 (not 4.8/3.6 as a clean
    descending stair) - a duplicate value in the live formula, not a data-read error.

BREAKOUT AREA (Handle/Cheat/High Handle/Low Cheat, PART I, 10 pts) - these are
O'Neil cup-with-handle sub-pattern classifications with no mechanical definition
anywhere in the pipeline or the addendum. Approximated as a 2-tier proxy using
already-computed signals: TightBase(t-1) AND breakout+volume -> "Handle" (10, the
real sheet's top score); breakout+volume without a clean prior tight base ->
"Cheat" (8). The "High Handle"/"Low Cheat" sub-variants (both score 4 in the real
sheet) are not distinguished - this collapses 4 categories to 2, a real
simplification, not a resolved formula.

LAST T (%) - the real formula (traced from PARAMETER row 9, dead branches removed):
  value >= 0.07        -> 0  (worst - the "test" broke down too far)
  0.04 <= value < 0.07  -> 1.5
  0.03 <= value < 0.04  -> 3.0 (peak - a tight, shallow final test)
  value < 0.03          -> 2.25
"value" itself is NOT defined anywhere in the source sheet/addendum as a computable
OHLCV quantity - proxied here as the largest 1-day-to-N-day pullback percentage
within the final LAST_T_WINDOW trading days of the base (the "last test" of support
before breakout). This is an interpretation, not a resolved ground truth - flag
whenever this row's contribution is discussed.

Shakeout needs real intraday Low (Close-only data can't show an intraday undercut
that recovers same-day) - downloaded separately, low_cache_2018_2026.csv.
"""
import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(__file__)
REPO_ROOT = os.path.dirname(HERE)
PRICE_CACHE = os.path.join(HERE, "price_cache_2018_2026.csv")
VOLUME_CACHE = os.path.join(HERE, "volume_cache_2018_2026.csv")
LOW_CACHE = os.path.join(HERE, "low_cache_2018_2026.csv")
SECTOR_HTML = os.path.join(REPO_ROOT, "set_stock_list", "listedCompanies_en_US.html")
TRADE_LOG_CSV = os.path.join(HERE, "equity_sim_trades_fullprocess_2020_2026.csv")
EQUITY_CSV = os.path.join(HERE, "equity_sim_curve_fullprocess_2020_2026.csv")

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

PRIOR_UPTREND_WINDOW = 63    # trading days of run-up measured immediately before the base - my assumption
LAST_T_WINDOW = 10           # sub-window at the end of the base to find "the last test" pullback - my assumption
VDU_LOOKBACK = 5             # days averaged for the VDU volume-dry-up check - my assumption
VDU_RATIO_MAX = 0.7          # VDU fires if recent-5d avg volume < 70% of the 50d average - my assumption
SHAKEOUT_UNDERCUT_PCT = 0.03  # Low must undercut the prior base low by >=3% then close back above it - my assumption

PASS_THRESHOLD = 75.0  # literal ACE bar now that PART I+II+III are all implemented (out of 100)

SIM_START = pd.Timestamp("2020-01-02")
SIM_END = pd.Timestamp("2026-06-30")
STARTING_CAPITAL = 100_000.0


def load_panel():
    close = pd.read_csv(PRICE_CACHE, index_col=0, parse_dates=True).sort_index()
    vol = pd.read_csv(VOLUME_CACHE, index_col=0, parse_dates=True).sort_index()
    low = pd.read_csv(LOW_CACHE, index_col=0, parse_dates=True).sort_index()
    close, vol = close.align(vol, join="inner")
    close, low = close.align(low, join="inner")
    vol = vol.reindex(columns=close.columns)
    low = low.reindex(columns=close.columns)
    return close, vol, low


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


def select_ge(value_df, thresholds_desc, points_desc, below_points):
    """thresholds_desc/points_desc: parallel, HIGHEST threshold first (matches how the
    real sheet's nested-IF cascades read top to bottom). First matching (>=) threshold
    wins - implemented via np.select checked in the given (descending) order, which is
    exactly right since np.select takes the first True condition."""
    arr = value_df.values
    conds = [arr >= t for t in thresholds_desc]
    out = np.select(conds, points_desc, default=below_points)
    return pd.DataFrame(out, index=value_df.index, columns=value_df.columns).where(value_df.notna())


def select_le(value_df, thresholds_asc, points_desc, above_points):
    """thresholds_asc/points_desc: ascending thresholds, parallel descending points -
    tightest (<=) threshold wins, first match in ascending order."""
    arr = value_df.values
    conds = [arr <= t for t in thresholds_asc]
    out = np.select(conds, points_desc, default=above_points)
    return pd.DataFrame(out, index=value_df.index, columns=value_df.columns).where(value_df.notna())


def compute_signals(close, vol, low):
    rs_rank = compute_rs_rank(close)

    high_n = close.rolling(BASE_LOOKBACK).max()
    low_n = close.rolling(BASE_LOOKBACK).min()
    base_depth_pct = (high_n - low_n) / low_n
    tight_base = base_depth_pct <= BASE_TIGHTNESS_MAX
    tight_base_prev = tight_base.shift(1)

    prior_high = close.shift(1).rolling(BREAKOUT_LOOKBACK).max()
    vol_ratio = vol / vol.rolling(VOLUME_AVG_WINDOW).mean()
    breakout_with_volume = (close > prior_high) & (vol_ratio >= BREAKOUT_VOLUME_MULT)

    high_252d = close.rolling(252).max()
    high_to_close_252d = high_252d / close - 1.0
    ath_running = close.expanding().max()  # data-bounded "all-time" proxy (data starts 2018-10)
    ath_dist = ath_running / close - 1.0
    avg_value_20d = (close * vol).rolling(20).mean()

    sector_map = load_sector_map(close.columns)
    sector_rs = rs_rank.T.groupby(sector_map).mean().T
    sector_rs_per_stock = pd.DataFrame(
        {s: sector_rs[sector_map[s]] if pd.notna(sector_map[s]) and sector_map[s] in sector_rs.columns
         else pd.Series(np.nan, index=rs_rank.index)
         for s in close.columns}
    )

    market_index = (1 + close.pct_change(fill_method=None).mean(axis=1).fillna(0)).cumprod()
    regime_up = market_index > market_index.rolling(MARKET_TREND_WINDOW).mean()
    ma_trail = close.rolling(TRAIL_MA_WINDOW).mean()
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()

    # --- PART I (50) ---
    # RS SCORE: real formula is a discrete bucket lookup on the RS percentile, not continuous.
    rs_pct_x100 = rs_rank * 100.0
    rs_score = select_ge(rs_pct_x100, [97, 95, 90, 85, 80], [40, 36, 32, 16, 8], below_points=0)
    # BREAKOUT AREA: 2-tier proxy (see module docstring) of the real Handle/Cheat/High Handle/Low Cheat
    # classification - real top score is 10 (Handle), 8 (Cheat); High Handle/Low Cheat (both 4) not modeled.
    tight_base_prev_bool = tight_base_prev.fillna(False).astype(bool)
    breakout_area = pd.DataFrame(
        np.where(tight_base_prev_bool.values & breakout_with_volume.values, 10.0,
                 np.where(breakout_with_volume.values, 8.0, 0.0)),
        index=close.index, columns=close.columns,
    )

    # --- PART II (30) ---
    # PRIOR UPTREND (6): return over PRIOR_UPTREND_WINDOW days ending BASE_LOOKBACK days ago
    # (the run-up right before the base started). Real formula's >=50%/>=25% tiers both
    # score 3.6 (a duplicate value in the live sheet, replicated as-is, not "fixed").
    prior_uptrend_pct = close.shift(BASE_LOOKBACK) / close.shift(BASE_LOOKBACK + PRIOR_UPTREND_WINDOW) - 1.0
    row_uptrend = select_ge(prior_uptrend_pct, [1.0, 0.75, 0.5, 0.25, 0.0], [6.0, 5.4, 3.6, 3.6, 2.4], below_points=0.0)

    # BASE DEPTH (6): real formula's >=30% branch is dead code (see docstring) - replicated faithfully.
    row_depth = pd.DataFrame(
        np.where(base_depth_pct.values < 0.1, 3.0,
                 np.where(base_depth_pct.values < 0.25, 6.0, 3.0)),
        index=close.index, columns=close.columns,
    ).where(base_depth_pct.notna())

    # BASE LENGTH (6): live formula already reflects the addendum SS1b flip (>=45 scores full 6).
    tight_10 = ((close.rolling(10).max() - close.rolling(10).min()) / close.rolling(10).min()) <= BASE_TIGHTNESS_MAX
    tight_15 = ((close.rolling(15).max() - close.rolling(15).min()) / close.rolling(15).min()) <= BASE_TIGHTNESS_MAX
    tight_45 = ((close.rolling(45).max() - close.rolling(45).min()) / close.rolling(45).min()) <= BASE_TIGHTNESS_MAX
    row_length = pd.DataFrame(
        np.select(
            [tight_45.shift(1).fillna(False).values, tight_15.shift(1).fillna(False).values,
             tight_10.shift(1).fillna(False).values],
            [6.0, 4.8, 3.0],
            default=1.5,
        ),
        index=close.index, columns=close.columns,
    )

    # LAST T (3): proxy = largest high-to-low pullback within the final LAST_T_WINDOW days
    # of the base (see docstring - "value" is an interpretation, formula/buckets are exact).
    sub_high = close.rolling(LAST_T_WINDOW).max().shift(1)
    sub_low = close.rolling(LAST_T_WINDOW).min().shift(1)
    last_t_pct = (sub_high - sub_low) / sub_high
    row_last_t = pd.DataFrame(
        np.select(
            [last_t_pct.values >= 0.07, last_t_pct.values >= 0.04, last_t_pct.values >= 0.03],
            [0.0, 1.5, 3.0],
            default=2.25,
        ),
        index=close.index, columns=close.columns,
    ).where(last_t_pct.notna())

    # VDU (1)
    vdu = (vol.rolling(VDU_LOOKBACK).mean().shift(1) < VDU_RATIO_MAX * vol.rolling(VOLUME_AVG_WINDOW).mean().shift(1))
    row_vdu = vdu.astype(float) * 1.0

    # Shakeout (1): Low undercuts the base's established low then Close recovers back above it, same day.
    base_low_established = low.rolling(BASE_LOOKBACK).min().shift(1)
    shakeout_day = (low < base_low_established * (1 - SHAKEOUT_UNDERCUT_PCT)) & (close >= base_low_established)
    shakeout_in_base = shakeout_day.rolling(BASE_LOOKBACK).max().fillna(0).astype(bool)
    row_shakeout = shakeout_in_base.astype(float) * 1.0

    # 52WH DISTANCE (3) / ATH DISTANCE (2): both effectively 3-tier after collapsing dead branches.
    row_52wh = select_le(high_to_close_252d, [0.05, 0.15], [3.0, 1.2], above_points=0.0)
    row_ath = select_le(ath_dist, [0.05, 0.15], [2.0, 0.8], above_points=0.0)

    # MA10/20 SUPPORT (2): yesterday's close above both MAs.
    ma_support = (close.shift(1) > ma10.shift(1)) & (close.shift(1) > ma20.shift(1))
    row_ma_support = ma_support.astype(float) * 2.0

    part2_total = (row_uptrend.fillna(0) + row_depth.fillna(0) + row_length.fillna(0) + row_last_t.fillna(0)
                   + row_vdu.fillna(0) + row_shakeout.fillna(0) + row_52wh.fillna(0) + row_ath.fillna(0)
                   + row_ma_support.fillna(0))

    # --- PART III (20) - unchanged from simulate_full_scoring_2020_2026.py, confirmed against
    # the real PARAMETER cells (VolumeRatio/TightBase/HighToClose_252d/SectorRS all matched
    # exactly) except AvgValue_20d, whose real cutoffs (1M/5M/20M THB) replace the earlier guess.
    row_breakout_confirmed = breakout_with_volume.astype(float) * 4.0
    row_vol_ratio = select_ge(vol_ratio, [3.0, 2.0, 1.5, 1.0], [4.0, 3.4, 2.8, 2.2], below_points=1.2)
    row_tight_base = tight_base.astype(float) * 4.0
    row_h2c = select_ge(1 - high_to_close_252d, [0.95, 0.85, 0.70], [4.0, 2.8, 1.6], below_points=0.0)
    row_sector_rs = select_ge(sector_rs_per_stock, [0.8, 0.6, 0.4], [2.0, 1.4, 0.8], below_points=0.0)
    row_avg_value = select_ge(avg_value_20d, [20_000_000, 5_000_000, 1_000_000], [2.0, 1.4, 0.8], below_points=0.0)

    part3_total = (row_breakout_confirmed.fillna(0) + row_vol_ratio.fillna(0) + row_tight_base.fillna(0)
                   + row_h2c.fillna(0) + row_sector_rs.fillna(0) + row_avg_value.fillna(0))

    total_score = rs_score.fillna(0) + breakout_area.fillna(0) + part2_total + part3_total
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
    close, vol, low = load_panel()
    print(f"Panel: {close.shape}, {close.index.min()} to {close.index.max()}")

    rs_rank, total_score, entry_signal, regime_up, ma_trail = compute_signals(close, vol, low)
    sim_dates = close.index[(close.index >= SIM_START) & (close.index <= SIM_END)]
    n_cand = entry_signal.loc[sim_dates].sum(axis=1)
    print(f"Candidates/day passing RS>=80 AND score>=75: mean={n_cand.mean():.2f}, "
          f"median={n_cand.median():.0f}, days with 0 candidates={ (n_cand==0).sum() }/{len(n_cand)}")

    equity_df, trade_df = simulate(close, rs_rank, total_score, entry_signal, regime_up, ma_trail)
    equity_df.to_csv(EQUITY_CSV)
    trade_df.to_csv(TRADE_LOG_CSV, index=False)

    print(f"\n=== Full literal ACE>=75/100 scoring, trailing-MA50/-8%stop exit ===")
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
