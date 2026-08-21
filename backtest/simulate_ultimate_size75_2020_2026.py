"""
Everything stacked: the fixed literal ACE>=75/100 scoring (PART I+II+III, both real
spreadsheet bugs corrected, from simulate_full_process_fixed_2020_2026.py) PLUS the
MDD>15% sizing throttle + 5-consecutive-loss halt (from simulate_mdd_sizing_2020_2026.py)
PLUS round-trip transaction costs (from simulate_txn_cost_2020_2026.py). Exit rule is
still trailing-MA50/-8%-stop (the "main line" exit used throughout this doc) - the
2R/3R/5R alternative was a separate exploratory comparison, not stacked here unless
asked.

Signal/scoring section is identical to simulate_full_process_fixed_2020_2026.py - see
that script's docstring for full formula provenance and documented assumptions
(Breakout Area 2-tier proxy, Last T's interpretation, Prior Uptrend window, etc.).
Execution section adds:
  - MDD throttle: once portfolio drawdown from peak equity exceeds 15%, REDUCE
    sizing to a floor (3%) but entries CONTINUE (not a full halt). An earlier
    version of this script (and the standalone simulate_mdd_sizing_2020_2026.py,
    whose "near-free lunch" result is currently the addendum's headline finding)
    fully halted entries instead - verified on disk: that script's equity curve
    freezes at exactly 232,561.56 THB for 953 straight days (2022-08-02 onward,
    n_positions=0) because an all-cash, fully-halted portfolio can never close a
    peak-relative drawdown gap - the only lever that could (new capital deployment)
    is exactly what the halt forbids. The "-47%->-16% DD for near-zero CAGR cost"
    reading of that result was reading a portfolio that stopped operating in month
    32 of a 78-month backtest, not one trading safely through a drawdown. Fixed here
    by never blocking entries on MDD alone, only reducing size.
  - Loss-streak halt: after 5 consecutive losing exits, halt new entries for a FIXED
    10-trading-day cool-down, then auto-resume regardless of streak status. (This one
    genuinely calls for a full stop per the addendum's SS4 text, but "until the next
    win" has the same deadlock risk if the halt itself prevents ever getting a new
    trade to win - the fixed cool-down avoids that.)
  - Transaction cost: 0.1665%/side (commission + SET/clearing fees + VAT, same
    assumption as the txn-cost run) deducted on every buy and sell - charged ONCE per
    side (an earlier version of this script deducted it twice: once by shrinking the
    shares bought via `net_alloc = alloc - cost`, and again via `cash -= alloc` at
    full notional. Fixed to charge cash the `alloc + cost` total and buy shares at
    the full `alloc`, matching simulate_txn_cost_2020_2026.py's correct pattern).
  - Swap-in/swap-out (added 2026-08-21): when the book is full (20/20) and a new
    candidate scores at least SWAP_MIN_EDGE (5 points/100) above the CURRENT score
    of the weakest held position, exit the weakest holding and enter the new
    candidate same-day. Without this, well-qualifying signals (RS>=80, score>=75)
    were silently skipped purely because no slot was free - verified on real
    symbols: HANA.BK fired the entry signal 9 times across 2020-2026 (scores 75-86)
    and was never once bought, because every single one of those 9 days already had
    20/20 positions filled; KCE.BK fired 17 times but only got in on its first 3
    (2020-2021, before the book filled up) - every later signal, including three in
    2026, was blocked the same way. SWAP_MIN_EDGE is my own assumption (not in any
    source doc) - meant to avoid thrashing the book on trivial score differences.
  - NAV+2% cushion escalation (added 2026-08-21, per addendum SS3's "upper tiers
    15-20%, gated behind NAV+2% cushion" - previously never implemented in any run,
    all prior sims only ever sized DOWN from the 5% baseline): the source doc doesn't
    specify the exact escalation mechanics, so this is an interpretation, not a
    resolved formula. Rule used here: escalate to the top of the stated band (20%)
    whenever equity is AT a fresh all-time high AND that high is at least 2% above
    the high-water-mark from CUSHION_LOOKBACK_DAYS (20 trading days) ago - i.e.
    genuine, sustained new-high progress, not a single noisy tick. Otherwise sizing
    is the same 5%/3.75%/3%/2.25% ladder as before (MDD throttle still overrides
    escalation - can't be both in a >15% drawdown and at a fresh cushioned high).
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
TRADE_LOG_CSV = os.path.join(HERE, "equity_sim_trades_ultimate_size75_2020_2026.csv")
EQUITY_CSV = os.path.join(HERE, "equity_sim_curve_ultimate_size75_2020_2026.csv")
OPEN_POSITIONS_CSV = os.path.join(HERE, "open_positions_ultimate_size75_2020_2026.csv")

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
POSITION_SIZE_PCT = 0.075
REGIME_DOWN_SIZE_MULT = 0.75
MAX_POSITIONS = 20

PRIOR_UPTREND_WINDOW = 63
LAST_T_WINDOW = 10
VDU_LOOKBACK = 5
VDU_RATIO_MAX = 0.7
SHAKEOUT_UNDERCUT_PCT = 0.03

PASS_THRESHOLD = 75.0

# --- stacked execution-layer knobs ---
MDD_THROTTLE_TRIGGER = 0.15  # reduce sizing (not halt) once portfolio DD from peak exceeds this
MDD_THROTTLE_SIZE_PCT = 0.03  # sizing floor while throttled
MDD_RECOVERY_BAND = 0.05     # throttle lifts once equity is back within this % of the prior peak
LOSS_STREAK_HALT_N = 5       # halt new entries after this many consecutive losing exits
LOSS_STREAK_COOLDOWN_DAYS = 10  # fixed cool-down before auto-resuming (see docstring bug note)
ROUNDTRIP_COST_PCT_PER_SIDE = 0.001665  # commission + SET/clearing fees + VAT, per side

ESCALATION_SIZE_PCT = 0.20    # top of the addendum's stated 15-20% band
CUSHION_LOOKBACK_DAYS = 20    # "sustained" new-high check window
CUSHION_MIN_GROWTH = 0.02     # the "NAV+2%" cushion itself

SWAP_MIN_EDGE = 1000.0        # DISABLED by default (see docstring: tested at 5.0, made results
                              # worse - 594,767->415,072 THB, cuts winners short via trail_ma50's
                              # +13.0% avg getting replaced by swap_out's +5.6% avg). Set back to
                              # ~5.0 only to reproduce that (rejected) experiment.

SIM_START = pd.Timestamp("2020-01-02")
SIM_END = pd.Timestamp("2026-08-20")  # latest date in the cached price panel (today, 2026-08-21)
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
    arr = value_df.values
    conds = [arr >= t for t in thresholds_desc]
    out = np.select(conds, points_desc, default=below_points)
    return pd.DataFrame(out, index=value_df.index, columns=value_df.columns).where(value_df.notna())


def select_le(value_df, thresholds_asc, points_desc, above_points):
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
    ath_running = close.expanding().max()
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

    rs_pct_x100 = rs_rank * 100.0
    rs_score = select_ge(rs_pct_x100, [97, 95, 90, 85, 80], [40, 36, 32, 16, 8], below_points=0)
    tight_base_prev_bool = tight_base_prev.fillna(False).astype(bool)
    breakout_area = pd.DataFrame(
        np.where(tight_base_prev_bool.values & breakout_with_volume.values, 10.0,
                 np.where(breakout_with_volume.values, 8.0, 0.0)),
        index=close.index, columns=close.columns,
    )

    prior_uptrend_pct = close.shift(BASE_LOOKBACK) / close.shift(BASE_LOOKBACK + PRIOR_UPTREND_WINDOW) - 1.0
    row_uptrend = select_ge(prior_uptrend_pct, [1.0, 0.75, 0.5, 0.25, 0.0], [6.0, 5.4, 4.8, 3.6, 2.4], below_points=0.0)

    row_depth = pd.DataFrame(
        np.select(
            [base_depth_pct.values < 0.1, base_depth_pct.values < 0.25, base_depth_pct.values >= 0.3],
            [3.0, 6.0, 1.8],
            default=3.0,
        ),
        index=close.index, columns=close.columns,
    ).where(base_depth_pct.notna())

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

    vdu = (vol.rolling(VDU_LOOKBACK).mean().shift(1) < VDU_RATIO_MAX * vol.rolling(VOLUME_AVG_WINDOW).mean().shift(1))
    row_vdu = vdu.astype(float) * 1.0

    base_low_established = low.rolling(BASE_LOOKBACK).min().shift(1)
    shakeout_day = (low < base_low_established * (1 - SHAKEOUT_UNDERCUT_PCT)) & (close >= base_low_established)
    shakeout_in_base = shakeout_day.rolling(BASE_LOOKBACK).max().fillna(0).astype(bool)
    row_shakeout = shakeout_in_base.astype(float) * 1.0

    row_52wh = select_le(high_to_close_252d, [0.05, 0.15], [3.0, 1.2], above_points=0.0)
    row_ath = select_le(ath_dist, [0.05, 0.15], [2.0, 0.8], above_points=0.0)

    ma_support = (close.shift(1) > ma10.shift(1)) & (close.shift(1) > ma20.shift(1))
    row_ma_support = ma_support.astype(float) * 2.0

    part2_total = (row_uptrend.fillna(0) + row_depth.fillna(0) + row_length.fillna(0) + row_last_t.fillna(0)
                   + row_vdu.fillna(0) + row_shakeout.fillna(0) + row_52wh.fillna(0) + row_ath.fillna(0)
                   + row_ma_support.fillna(0))

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

    return rs_rank, total_score, entry_signal, regime_up, ma_trail, market_index


def simulate(close, rs_rank, total_score, entry_signal, regime_up, ma_trail):
    dates = close.index[(close.index >= SIM_START) & (close.index <= SIM_END)]
    cash = STARTING_CAPITAL
    positions = {}
    equity_curve = []
    trade_log = []

    running_peak = STARTING_CAPITAL
    peak_history = []  # running_peak recorded each day, for the cushion lookback
    mdd_throttled = False
    consec_losses = 0
    loss_streak_cooldown_remaining = 0
    n_mdd_throttled_days = 0
    n_loss_streak_halted_days = 0
    n_escalated_days = 0

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
                gross_proceeds = shares * p
                net_proceeds = gross_proceeds * (1 - ROUNDTRIP_COST_PCT_PER_SIDE)
                cash += net_proceeds
                ret = p / entry_price - 1
                trade_log.append({
                    "symbol": sym,
                    "entry_date": positions[sym]["entry_date"], "exit_date": d,
                    "entry_price": entry_price, "exit_price": p,
                    "shares": shares,
                    "alloc_thb": positions[sym]["alloc_thb"],
                    "equity_at_entry": positions[sym]["equity_at_entry"],
                    "size_pct_used": positions[sym]["size_pct_used"],
                    "return_pct": ret,
                    "pnl_thb": gross_proceeds - positions[sym]["alloc_thb"],
                    "reason": "hard_stop" if hard_stop_hit else "trail_ma50",
                })
                del positions[sym]
                if ret <= 0:
                    consec_losses += 1
                    if consec_losses >= LOSS_STREAK_HALT_N:
                        loss_streak_cooldown_remaining = LOSS_STREAK_COOLDOWN_DAYS
                else:
                    consec_losses = 0

        held_value = sum(positions[s]["shares"] * px.get(s, positions[s]["entry_price"]) for s in positions)
        equity = cash + held_value
        running_peak = max(running_peak, equity)
        current_dd = equity / running_peak - 1

        if current_dd <= -MDD_THROTTLE_TRIGGER:
            mdd_throttled = True
        elif mdd_throttled and equity >= running_peak * (1 - MDD_RECOVERY_BAND):
            mdd_throttled = False
        loss_streak_halted = loss_streak_cooldown_remaining > 0
        if loss_streak_halted:
            loss_streak_cooldown_remaining -= 1
        if mdd_throttled:
            n_mdd_throttled_days += 1
        if loss_streak_halted:
            n_loss_streak_halted_days += 1

        peak_history.append(running_peak)
        at_fresh_high = equity >= running_peak
        cushioned = (
            len(peak_history) > CUSHION_LOOKBACK_DAYS
            and running_peak >= peak_history[-1 - CUSHION_LOOKBACK_DAYS] * (1 + CUSHION_MIN_GROWTH)
        )
        escalated = (not mdd_throttled) and at_fresh_high and cushioned
        if escalated:
            n_escalated_days += 1

        slots = MAX_POSITIONS - len(positions)
        # MDD only reduces sizing (see docstring bug note) - only the loss-streak
        # cooldown fully blocks new entries.
        if slots == 0 and not loss_streak_halted and len(positions) > 0:
            todays_signal = entry_signal.loc[d]
            candidates = todays_signal[todays_signal].index.difference(list(positions.keys()))
            if len(candidates) > 0:
                best_candidate = total_score.loc[d, candidates].idxmax()
                best_candidate_score = total_score.loc[d, best_candidate]
                held_scores = total_score.loc[d, list(positions.keys())]
                weakest_sym = held_scores.idxmin()
                weakest_score = held_scores.loc[weakest_sym]
                if pd.notna(best_candidate_score) and pd.notna(weakest_score) and \
                        best_candidate_score >= weakest_score + SWAP_MIN_EDGE:
                    p_exit = px.get(weakest_sym, np.nan)
                    if pd.notna(p_exit):
                        pos = positions[weakest_sym]
                        shares = pos["shares"]
                        gross_proceeds = shares * p_exit
                        net_proceeds = gross_proceeds * (1 - ROUNDTRIP_COST_PCT_PER_SIDE)
                        cash += net_proceeds
                        ret = p_exit / pos["entry_price"] - 1
                        trade_log.append({
                            "symbol": weakest_sym,
                            "entry_date": pos["entry_date"], "exit_date": d,
                            "entry_price": pos["entry_price"], "exit_price": p_exit,
                            "shares": shares, "alloc_thb": pos["alloc_thb"],
                            "equity_at_entry": pos["equity_at_entry"], "size_pct_used": pos["size_pct_used"],
                            "return_pct": ret, "pnl_thb": gross_proceeds - pos["alloc_thb"],
                            "reason": "swap_out",
                        })
                        del positions[weakest_sym]
                        if ret <= 0:
                            consec_losses += 1
                            if consec_losses >= LOSS_STREAK_HALT_N:
                                loss_streak_cooldown_remaining = LOSS_STREAK_COOLDOWN_DAYS
                        else:
                            consec_losses = 0

        slots = MAX_POSITIONS - len(positions)
        if slots > 0 and not loss_streak_halted:
            todays_signal = entry_signal.loc[d]
            candidates = todays_signal[todays_signal].index.difference(list(positions.keys()))
            if len(candidates) > 0:
                cand_score = total_score.loc[d, candidates].sort_values(ascending=False)
                chosen = cand_score.index[:slots]
                if mdd_throttled:
                    size_pct = MDD_THROTTLE_SIZE_PCT
                elif escalated:
                    size_pct = ESCALATION_SIZE_PCT
                else:
                    size_pct = POSITION_SIZE_PCT
                size_mult = 1.0 if bool(regime_up.loc[d]) else REGIME_DOWN_SIZE_MULT
                for sym in chosen:
                    p = px.get(sym, np.nan)
                    if pd.isna(p) or p <= 0:
                        continue
                    alloc = min(equity * size_pct * size_mult, cash / (1 + ROUNDTRIP_COST_PCT_PER_SIDE))
                    if alloc <= 0:
                        continue
                    cost = alloc * ROUNDTRIP_COST_PCT_PER_SIDE
                    shares = alloc / p
                    cash -= alloc + cost
                    positions[sym] = {
                        "shares": shares, "entry_price": p, "entry_date": d,
                        "alloc_thb": alloc, "equity_at_entry": equity,
                        "size_pct_used": size_pct * size_mult,
                    }

        held_value = sum(positions[s]["shares"] * px.get(s, positions[s]["entry_price"]) for s in positions)
        equity = cash + held_value
        equity_curve.append((d, equity, cash, len(positions), mdd_throttled, loss_streak_halted))

    equity_df = pd.DataFrame(
        equity_curve, columns=["date", "equity", "cash", "n_positions", "mdd_throttled", "loss_streak_halted"]
    ).set_index("date")
    trade_df = pd.DataFrame(trade_log)
    print(f"MDD-throttled days (reduced size, still trading): {n_mdd_throttled_days}, "
          f"loss-streak-halted days: {n_loss_streak_halted_days}, "
          f"escalated (20%) days: {n_escalated_days} (of {len(dates)})")

    last_px = close.loc[dates[-1]]
    open_rows = []
    for sym, pos in positions.items():
        p = last_px.get(sym, np.nan)
        open_rows.append({
            "symbol": sym, "entry_date": pos["entry_date"], "entry_price": pos["entry_price"],
            "shares": pos["shares"], "alloc_thb": pos["alloc_thb"], "size_pct_used": pos["size_pct_used"],
            "last_date": dates[-1], "last_price": p,
            "unrealized_return_pct": (p / pos["entry_price"] - 1) if pd.notna(p) else np.nan,
            "market_value_thb": pos["shares"] * p if pd.notna(p) else np.nan,
        })
    open_df = pd.DataFrame(open_rows).sort_values("entry_date") if open_rows else pd.DataFrame(open_rows)
    return equity_df, trade_df, open_df


def max_drawdown(equity_sr):
    running_max = equity_sr.cummax()
    return (equity_sr / running_max - 1).min()


def cagr(equity_sr):
    n_years = (equity_sr.index[-1] - equity_sr.index[0]).days / 365.25
    return (equity_sr.iloc[-1] / equity_sr.iloc[0]) ** (1 / n_years) - 1


def main():
    close, vol, low = load_panel()
    print(f"Panel: {close.shape}, {close.index.min()} to {close.index.max()}")

    rs_rank, total_score, entry_signal, regime_up, ma_trail, market_index = compute_signals(close, vol, low)
    sim_dates = close.index[(close.index >= SIM_START) & (close.index <= SIM_END)]
    n_cand = entry_signal.loc[sim_dates].sum(axis=1)
    print(f"Candidates/day passing RS>=80 AND score>=75: mean={n_cand.mean():.2f}, "
          f"median={n_cand.median():.0f}, days with 0 candidates={(n_cand==0).sum()}/{len(n_cand)}")

    equity_df, trade_df, open_df = simulate(close, rs_rank, total_score, entry_signal, regime_up, ma_trail)
    bench_sr = market_index.loc[equity_df.index]
    bench_sr = bench_sr / bench_sr.iloc[0] * STARTING_CAPITAL
    equity_df["benchmark"] = bench_sr
    equity_df.to_csv(EQUITY_CSV)
    trade_df.to_csv(TRADE_LOG_CSV, index=False)
    open_df.to_csv(OPEN_POSITIONS_CSV, index=False)
    print(f"\n=== Open positions as of {equity_df.index[-1].date()} ({len(open_df)}) ===")
    print(open_df.to_string(index=False))

    print(f"\n=== Everything stacked: fixed ACE>=75/100 + MDD/loss-streak throttle + txn costs ===")
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
