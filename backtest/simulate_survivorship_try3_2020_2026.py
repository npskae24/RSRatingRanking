"""
Try 3: closes Try 2's "no volume, RS-gate-only proxy" gap for as many names
as yfinance still has data for. Same mechanics as
simulate_survivorship_2020_2026.py (Try 1) - splice delisted names into the
panel, force a full write-off (-100%) on any position still open when a
ticker's data ends - but now covers Try 1's 14 confirmed-delisted names PLUS
4 more found via download_try2_names.py out of Try 2's 68-ticker OneDrive
existence list (SLM.BK, STHAI.BK, ACAP.BK, BPP.BK - the other 60/68,
including the two confirmed real fraud cases JKN.BK and STARK.BK, still have
ZERO data anywhere on yfinance - Yahoo has purged them entirely, so they
remain unmeasurable by this method no matter what).

Total measured now: 18/98 exclusion_list.txt names + 18/68 Try-2 OneDrive
gone-tickers (14 overlap - wait, no overlap; these are two disjoint
universes: exclusion_list.txt-derived 14, and OneDrive-derived 4, both
confirmed genuinely delisted with usable price history). 18 tickers total
spliced in, full production signal (RS>=80pct AND TightBase AND
BreakoutVolumeConfirmed AND score>=75), same as simulate_ultimate_2020_2026.
"""
import os
import numpy as np
import pandas as pd

from simulate_ultimate_2020_2026 import (
    compute_signals, max_drawdown, cagr,
    STARTING_CAPITAL, SIM_START, SIM_END, MAX_POSITIONS,
    HARD_STOP_PCT, POSITION_SIZE_PCT, MDD_THROTTLE_TRIGGER, MDD_THROTTLE_SIZE_PCT,
    MDD_RECOVERY_BAND, LOSS_STREAK_HALT_N, LOSS_STREAK_COOLDOWN_DAYS,
    ROUNDTRIP_COST_PCT_PER_SIDE, ESCALATION_SIZE_PCT, CUSHION_LOOKBACK_DAYS,
    CUSHION_MIN_GROWTH, SWAP_MIN_EDGE, REGIME_DOWN_SIZE_MULT,
)

HERE = os.path.dirname(__file__)
PRICE_CACHE = os.path.join(HERE, "price_cache_2018_2026.csv")
VOLUME_CACHE = os.path.join(HERE, "volume_cache_2018_2026.csv")
LOW_CACHE = os.path.join(HERE, "low_cache_2018_2026.csv")
DELISTED_PRICE = os.path.join(HERE, "delisted_price_cache.csv")
DELISTED_VOLUME = os.path.join(HERE, "delisted_volume_cache.csv")
DELISTED_LOW = os.path.join(HERE, "delisted_low_cache.csv")
TRY2_PRICE = os.path.join(HERE, "try2_price_cache.csv")
TRY2_VOLUME = os.path.join(HERE, "try2_volume_cache.csv")
TRY2_LOW = os.path.join(HERE, "try2_low_cache.csv")
EQUITY_CSV = os.path.join(HERE, "equity_sim_curve_survivorship_try3_2020_2026.csv")
TRADE_LOG_CSV = os.path.join(HERE, "equity_sim_trades_survivorship_try3_2020_2026.csv")

DELISTED_CUTOFF = pd.Timestamp("2026-08-18")
TERMINAL_LOSS_PCT = 1.0


def _genuine_delisted(price_path):
    df = pd.read_csv(price_path, index_col=0, parse_dates=True).sort_index()
    last_valid = df.apply(lambda s: s.last_valid_index())
    syms = last_valid[last_valid < DELISTED_CUTOFF].index.tolist()
    return df, last_valid, syms


def load_panel():
    close = pd.read_csv(PRICE_CACHE, index_col=0, parse_dates=True).sort_index()
    vol = pd.read_csv(VOLUME_CACHE, index_col=0, parse_dates=True).sort_index()
    low = pd.read_csv(LOW_CACHE, index_col=0, parse_dates=True).sort_index()
    close, vol = close.align(vol, join="inner")
    close, low = close.align(low, join="inner")
    vol = vol.reindex(columns=close.columns)
    low = low.reindex(columns=close.columns)

    all_last_valid = []
    for price_path, vol_path, low_path in [
        (DELISTED_PRICE, DELISTED_VOLUME, DELISTED_LOW),
        (TRY2_PRICE, TRY2_VOLUME, TRY2_LOW),
    ]:
        d_close, last_valid, syms = _genuine_delisted(price_path)
        d_vol = pd.read_csv(vol_path, index_col=0, parse_dates=True).sort_index()
        d_low = pd.read_csv(low_path, index_col=0, parse_dates=True).sort_index()
        print(f"Splicing in {len(syms)} genuinely-delisted tickers from {os.path.basename(price_path)}: {syms}")
        close = close.join(d_close[syms], how="outer")
        vol = vol.join(d_vol[syms], how="outer")
        low = low.join(d_low[syms], how="outer")
        all_last_valid.append(last_valid.loc[syms])

    close = close.sort_index()
    vol = vol.reindex(index=close.index, columns=close.columns)
    low = low.reindex(index=close.index, columns=close.columns)
    delisted_last_valid = pd.concat(all_last_valid)
    return close, vol, low, delisted_last_valid


def simulate(close, total_score, entry_signal, regime_up, ma_trail, delisted_last_valid):
    dates = close.index[(close.index >= SIM_START) & (close.index <= SIM_END)]
    cash = STARTING_CAPITAL
    positions = {}
    equity_curve = []
    trade_log = []

    running_peak = STARTING_CAPITAL
    peak_history = []
    mdd_throttled = False
    consec_losses = 0
    loss_streak_cooldown_remaining = 0
    n_writeoffs = 0

    for d in dates:
        px = close.loc[d]

        for sym in list(positions.keys()):
            p = px.get(sym, np.nan)
            is_last_day = sym in delisted_last_valid.index and delisted_last_valid[sym] == d
            if pd.isna(p):
                if is_last_day:
                    entry_price = positions[sym]["entry_price"]
                    shares = positions[sym]["shares"]
                    ret = -TERMINAL_LOSS_PCT
                    proceeds = shares * entry_price * (1 - TERMINAL_LOSS_PCT)
                    cash += proceeds
                    trade_log.append({
                        "symbol": sym, "entry_date": positions[sym]["entry_date"], "exit_date": d,
                        "entry_price": entry_price, "exit_price": entry_price * (1 - TERMINAL_LOSS_PCT),
                        "shares": shares, "alloc_thb": positions[sym]["alloc_thb"],
                        "equity_at_entry": positions[sym]["equity_at_entry"],
                        "size_pct_used": positions[sym]["size_pct_used"],
                        "return_pct": ret, "pnl_thb": proceeds - positions[sym]["alloc_thb"],
                        "reason": "delisted_writeoff",
                    })
                    del positions[sym]
                    n_writeoffs += 1
                    consec_losses += 1
                    if consec_losses >= LOSS_STREAK_HALT_N:
                        loss_streak_cooldown_remaining = LOSS_STREAK_COOLDOWN_DAYS
                continue
            entry_price = positions[sym]["entry_price"]
            ma = ma_trail.at[d, sym] if sym in ma_trail.columns else np.nan
            hard_stop_hit = (p / entry_price - 1) <= -HARD_STOP_PCT
            trail_hit = (not pd.isna(ma)) and (p < ma)
            forced_writeoff = is_last_day and not (hard_stop_hit or trail_hit)
            if hard_stop_hit or trail_hit or forced_writeoff:
                shares = positions[sym]["shares"]
                if forced_writeoff:
                    exit_price = p * (1 - TERMINAL_LOSS_PCT)
                    ret = exit_price / entry_price - 1
                    net_proceeds = shares * exit_price
                    reason = "delisted_writeoff"
                    n_writeoffs += 1
                else:
                    exit_price = p
                    gross_proceeds = shares * p
                    net_proceeds = gross_proceeds * (1 - ROUNDTRIP_COST_PCT_PER_SIDE)
                    ret = p / entry_price - 1
                    reason = "hard_stop" if hard_stop_hit else "trail_ma50"
                cash += net_proceeds
                trade_log.append({
                    "symbol": sym, "entry_date": positions[sym]["entry_date"], "exit_date": d,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": shares, "alloc_thb": positions[sym]["alloc_thb"],
                    "equity_at_entry": positions[sym]["equity_at_entry"],
                    "size_pct_used": positions[sym]["size_pct_used"],
                    "return_pct": ret, "pnl_thb": net_proceeds - positions[sym]["alloc_thb"],
                    "reason": reason,
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

        peak_history.append(running_peak)
        at_fresh_high = equity >= running_peak
        cushioned = (
            len(peak_history) > CUSHION_LOOKBACK_DAYS
            and running_peak >= peak_history[-1 - CUSHION_LOOKBACK_DAYS] * (1 + CUSHION_MIN_GROWTH)
        )
        escalated = (not mdd_throttled) and at_fresh_high and cushioned

        slots = MAX_POSITIONS - len(positions)
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
                            "symbol": weakest_sym, "entry_date": pos["entry_date"], "exit_date": d,
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
        equity_curve.append((d, equity, cash, len(positions)))

    equity_df = pd.DataFrame(equity_curve, columns=["date", "equity", "cash", "n_positions"]).set_index("date")
    trade_df = pd.DataFrame(trade_log)
    print(f"Forced delisting write-offs: {n_writeoffs}")
    return equity_df, trade_df


def main():
    close, vol, low, delisted_last_valid = load_panel()
    print(f"Panel (with 18 delisted names spliced in): {close.shape}, {close.index.min()} to {close.index.max()}")

    rs_rank, total_score, entry_signal, regime_up, ma_trail, market_index = compute_signals(close, vol, low)
    equity_df, trade_df = simulate(close, total_score, entry_signal, regime_up, ma_trail, delisted_last_valid)
    equity_df.to_csv(EQUITY_CSV)
    trade_df.to_csv(TRADE_LOG_CSV, index=False)

    writeoffs = trade_df[trade_df["reason"] == "delisted_writeoff"] if len(trade_df) else trade_df
    print(f"\n=== Survivorship-corrected Try 3 (18/98+68 delisted names spliced in) ===")
    print(f"Start: {STARTING_CAPITAL:,.0f} THB on {equity_df.index[0].date()}")
    print(f"End:   {equity_df['equity'].iloc[-1]:,.0f} THB on {equity_df.index[-1].date()}")
    print(f"CAGR:  {cagr(equity_df['equity'])*100:.2f}%")
    print(f"Max drawdown: {max_drawdown(equity_df['equity'])*100:.2f}%")
    print(f"Total trades: {len(trade_df)}")
    print(f"Trades that were forced delisting write-offs: {len(writeoffs)}")
    if len(writeoffs):
        print(writeoffs[["symbol", "entry_date", "exit_date", "return_pct", "pnl_thb"]].to_string(index=False))
    if len(trade_df):
        wins = trade_df[trade_df["return_pct"] > 0]
        print(f"Win rate: {len(wins)/len(trade_df)*100:.1f}%")


if __name__ == "__main__":
    main()
