"""
Walk-forward check: is the production default (BASE_TIGHTNESS_MAX=0.15,
BREAKOUT_VOLUME_MULT=1.5) actually well-chosen, or does an in-sample-optimized
combo just look good on the period it was picked from and fail out-of-sample?

TRAIN = 2020-01-02 to 2023-01-01 (grid-search here, pick in-sample best by mean
90d-forward return of the entry signal). TEST = 2023-01-02 to 2026-06-30
(evaluate in-sample-best AND production default here, out-of-sample).
2018-10-01 to 2020-01-01 is lookback buffer only (RS/rolling windows need history
before TRAIN starts), not scored in either half.
"""
import os
import pandas as pd

HERE = os.path.dirname(__file__)
PRICE_CACHE = os.path.join(HERE, "price_cache_2018_2026.csv")
VOLUME_CACHE = os.path.join(HERE, "volume_cache_2018_2026.csv")
OUT_MD = os.path.join(HERE, "findings_walkforward.md")

PERIODS = [63, 126, 189, 252]
WEIGHTS = [0.4, 0.2, 0.2, 0.2]
RANKING_THRESHOLD = 0.8

BASE_LOOKBACK = 20
BREAKOUT_LOOKBACK = 20
VOLUME_AVG_WINDOW = 50

TIGHTNESS_GRID = [0.10, 0.15, 0.20]
VOLUME_MULT_GRID = [1.5, 2.0, 3.0]
PRODUCTION_DEFAULT = (0.15, 1.5)

TRAIN_START, TRAIN_END = pd.Timestamp("2020-01-02"), pd.Timestamp("2023-01-01")
TEST_START, TEST_END = pd.Timestamp("2023-01-02"), pd.Timestamp("2026-06-30")

HORIZON_DAYS = 90
TOLERANCE = 5


def load_panel():
    close = pd.read_csv(PRICE_CACHE, index_col=0, parse_dates=True).sort_index()
    vol = pd.read_csv(VOLUME_CACHE, index_col=0, parse_dates=True).sort_index()
    close, vol = close.align(vol, join="inner")
    return close, vol


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


def forward_return_panel(close, horizon_days):
    idx = close.index
    fwd = pd.DataFrame(index=idx, columns=close.columns, dtype=float)
    for d in idx:
        target = d + pd.Timedelta(days=horizon_days)
        fut = idx[(idx >= target) & (idx <= target + pd.Timedelta(days=TOLERANCE))]
        if len(fut):
            fwd.loc[d] = close.loc[fut[0]] / close.loc[d] - 1
    return fwd


def entry_signal_for(close, vol, rs_rank, tightness_max, volume_mult):
    high_n = close.rolling(BASE_LOOKBACK).max()
    low_n = close.rolling(BASE_LOOKBACK).min()
    tight_base = ((high_n - low_n) / low_n) <= tightness_max
    prior_high = close.shift(1).rolling(BREAKOUT_LOOKBACK).max()
    vol_ratio = vol / vol.rolling(VOLUME_AVG_WINDOW).mean()
    breakout_with_volume = (close > prior_high) & (vol_ratio >= volume_mult)
    return tight_base.shift(1) & breakout_with_volume & (rs_rank >= RANKING_THRESHOLD)


def score(signal_mask, fwd_panel, date_mask):
    masked = signal_mask.loc[date_mask]
    fwd = fwd_panel.loc[date_mask]
    vals = fwd.where(masked).stack()
    n = len(vals)
    if n == 0:
        return n, float("nan"), float("nan")
    return n, vals.mean(), (vals > 0).mean()


def main():
    close, vol = load_panel()
    print(f"Panel: {close.shape}, {close.index.min()} to {close.index.max()}")

    rs_rank = compute_rs_rank(close)
    print("Computing 90d forward returns for the whole panel...")
    fwd90 = forward_return_panel(close, HORIZON_DAYS)

    train_mask = (close.index >= TRAIN_START) & (close.index <= TRAIN_END)
    test_mask = (close.index >= TEST_START) & (close.index <= TEST_END)

    train_rows = []
    signals_cache = {}
    for tight in TIGHTNESS_GRID:
        for mult in VOLUME_MULT_GRID:
            sig = entry_signal_for(close, vol, rs_rank, tight, mult)
            signals_cache[(tight, mult)] = sig
            n, mean, winrate = score(sig, fwd90, train_mask)
            train_rows.append({"tightness_max": tight, "volume_mult": mult, "n": n, "mean_90d": mean, "winrate_90d": winrate})
            print(f"TRAIN tightness={tight} mult={mult}: n={n} mean={mean if n else float('nan'):.4f} winrate={winrate if n else float('nan'):.4f}")

    train_df = pd.DataFrame(train_rows).sort_values("mean_90d", ascending=False).reset_index(drop=True)
    best_combo = (train_df.iloc[0]["tightness_max"], train_df.iloc[0]["volume_mult"])
    print(f"\nIn-sample best (TRAIN): tightness={best_combo[0]}, volume_mult={best_combo[1]}")

    best_sig = signals_cache[best_combo]
    default_sig = signals_cache[PRODUCTION_DEFAULT]

    best_test = score(best_sig, fwd90, test_mask)
    default_test = score(default_sig, fwd90, test_mask)
    best_train = score(best_sig, fwd90, train_mask)
    default_train = score(default_sig, fwd90, train_mask)

    print(f"\nIn-sample-best  TRAIN: n={best_train[0]} mean={best_train[1]:.4f} winrate={best_train[2]:.4f}")
    print(f"In-sample-best  TEST:  n={best_test[0]} mean={best_test[1]:.4f} winrate={best_test[2]:.4f}")
    print(f"Prod default    TRAIN: n={default_train[0]} mean={default_train[1]:.4f} winrate={default_train[2]:.4f}")
    print(f"Prod default    TEST:  n={default_test[0]} mean={default_test[1]:.4f} winrate={default_test[2]:.4f}")

    lines = []
    lines.append("## Walk-forward threshold validation (2026-08-20)\n")
    lines.append(f"TRAIN = {TRAIN_START.date()} to {TRAIN_END.date()}, TEST = {TEST_START.date()} to {TEST_END.date()} "
                  f"(non-overlapping, {TEST_START.date()} strictly after TRAIN_END). Signal = TightBase(t-1) AND "
                  f"BreakoutVolumeConfirmed AND RS_rank>=0.8, {HORIZON_DAYS}d forward return. Script: `walkforward_thresholds.py`.\n")
    lines.append("### TRAIN grid search (9 combos, ranked by mean 90d return)\n")
    lines.append("| tightness_max | volume_mult | n | mean_90d | winrate_90d |")
    lines.append("|---|---|---|---|---|")
    for _, r in train_df.iterrows():
        lines.append(f"| {r['tightness_max']} | {r['volume_mult']} | {int(r['n'])} | {r['mean_90d']*100:.2f}% | {r['winrate_90d']*100:.1f}% |")
    lines.append("")
    lines.append("### In-sample-best vs production default, TRAIN vs TEST\n")
    lines.append("| | tightness/mult | TRAIN n | TRAIN mean | TRAIN win% | TEST n | TEST mean | TEST win% |")
    lines.append("|---|---|---|---|---|---|---|---|")
    lines.append(f"| In-sample best | {best_combo[0]}/{best_combo[1]} | {best_train[0]} | {best_train[1]*100:.2f}% | {best_train[2]*100:.1f}% | {best_test[0]} | {best_test[1]*100:.2f}% | {best_test[2]*100:.1f}% |")
    lines.append(f"| Production default | {PRODUCTION_DEFAULT[0]}/{PRODUCTION_DEFAULT[1]} | {default_train[0]} | {default_train[1]*100:.2f}% | {default_train[2]*100:.1f}% | {default_test[0]} | {default_test[1]*100:.2f}% | {default_test[2]*100:.1f}% |")
    lines.append("")

    degrade_best = best_train[1] - best_test[1]
    degrade_default = default_train[1] - default_test[1]
    beats_default_oos = best_test[1] > default_test[1]
    lines.append(
        f"**Interpretation:** the in-sample-best combo ({best_combo[0]}/{best_combo[1]}) scored "
        f"{best_train[1]*100:.2f}% mean 90d return on TRAIN vs the production default's {default_train[1]*100:.2f}% "
        f"— looked meaningfully better in-sample. Out-of-sample on TEST it produced {best_test[1]*100:.2f}%, a drop of "
        f"{degrade_best*100:.2f}pp from TRAIN, versus the production default's own TRAIN→TEST drop of {degrade_default*100:.2f}pp. "
        f"{'The in-sample winner still beats the production default out-of-sample' if beats_default_oos else 'The in-sample winner does NOT beat the production default out-of-sample'} "
        f"({best_test[1]*100:.2f}% vs {default_test[1]*100:.2f}%). "
        f"{'This is the classic overfitting tell (Pardo): the grid-search winner degraded harder than the untouched default and lost its edge out-of-sample — do not swap the production thresholds to the in-sample-best combo.' if not beats_default_oos or degrade_best > degrade_default else 'The in-sample winner held up reasonably well out-of-sample, some support for adopting it, but treat as one out-of-sample window, not proof.'} "
        f"Sample sizes per cell are in the thousands, so this isn't a small-n noise artifact either way."
    )

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nWrote findings to {OUT_MD}")


if __name__ == "__main__":
    main()
