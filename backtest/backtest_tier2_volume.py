import pandas as pd
import numpy as np

BACKUP = "D:/Stocktrading/RSRatingRanking-master/backup"

BASE_LOOKBACK = 20
BASE_TIGHTNESS_MAX = 0.15
BREAKOUT_LOOKBACK = 20
VOLUME_AVG_WINDOW = 50
BREAKOUT_VOLUME_MULT = 1.5
MARKET_TREND_WINDOW = 50

HORIZONS = [14, 28, 60, 90, 120, 180]
TOLERANCE = 5  # continuous daily data now, tighter tolerance than the sparse-panel backtests


def load():
    close = pd.read_csv(f"{BACKUP}/close_price.csv", index_col=0)
    close.index = pd.to_datetime(close.index)
    vol = pd.read_csv(f"{BACKUP}/volume.csv", index_col=0)
    vol.index = pd.to_datetime(vol.index)
    close, vol = close.align(vol, join="inner")
    return close.sort_index(), vol.sort_index()


def forward_returns(close, horizon_days):
    """For each date/symbol, forward return to the nearest date within
    [date+horizon, date+horizon+TOLERANCE]. Returns a DataFrame same shape as close."""
    idx = close.index
    target_pos = {}
    for d in idx:
        target = d + pd.Timedelta(days=horizon_days)
        fut = idx[(idx >= target) & (idx <= target + pd.Timedelta(days=TOLERANCE))]
        target_pos[d] = fut[0] if len(fut) else None

    fwd = pd.DataFrame(index=idx, columns=close.columns, dtype=float)
    for d in idx:
        td = target_pos[d]
        if td is None:
            continue
        fwd.loc[d] = close.loc[td] / close.loc[d] - 1
    return fwd


def main():
    close, vol = load()
    print(f"Panel: {close.shape}, {close.index.min()} to {close.index.max()}")

    df_high_n = close.rolling(BASE_LOOKBACK).max()
    df_low_n = close.rolling(BASE_LOOKBACK).min()
    tight_base = ((df_high_n - df_low_n) / df_low_n) <= BASE_TIGHTNESS_MAX

    prior_high = close.shift(1).rolling(BREAKOUT_LOOKBACK).max()
    vol_ratio = vol / vol.rolling(VOLUME_AVG_WINDOW).mean()
    breakout_price_only = close > prior_high
    breakout_with_volume = breakout_price_only & (vol_ratio >= BREAKOUT_VOLUME_MULT)

    market_index = (1 + close.pct_change(fill_method=None).mean(axis=1).fillna(0)).cumprod()
    market_regime_up_sr = market_index > market_index.rolling(MARKET_TREND_WINDOW).mean()
    # broadcast the per-date regime flag across all symbol columns (Series & DataFrame
    # aligns on columns by default, not rows, so this needs an explicit row-wise broadcast)
    market_regime_up = pd.DataFrame(
        np.repeat(market_regime_up_sr.values[:, None], close.shape[1], axis=1),
        index=close.index, columns=close.columns,
    )

    tight_base_prev = tight_base.shift(1)  # TightBase(t-1)

    signal_price_only = tight_base_prev & breakout_price_only
    signal_with_volume = tight_base_prev & breakout_with_volume
    signal_price_only_regime = signal_price_only & market_regime_up
    signal_with_volume_regime = signal_with_volume & market_regime_up

    results = {}
    for h in HORIZONS:
        print(f"computing forward returns for {h}d...")
        fwd = forward_returns(close, h)

        def summarize(mask):
            vals = fwd.where(mask).stack()
            n = len(vals)
            if n == 0:
                return (0, np.nan, np.nan)
            return (n, vals.mean(), (vals > 0).mean())

        baseline_mask = fwd.notna()
        results[h] = {
            "baseline": summarize(baseline_mask),
            "price_only": summarize(signal_price_only),
            "with_volume": summarize(signal_with_volume),
            "price_only_regime": summarize(signal_price_only_regime),
            "with_volume_regime": summarize(signal_with_volume_regime),
        }

    print("\n=== Results ===")
    print(f"{'Horizon':>8} {'Bucket':>20} {'n':>8} {'mean%':>10} {'winrate%':>10}")
    for h in HORIZONS:
        for name, (n, mean, wr) in results[h].items():
            m = f"{mean*100:.2f}" if not np.isnan(mean) else "NA"
            w = f"{wr*100:.1f}" if not np.isnan(wr) else "NA"
            print(f"{h:>8} {name:>20} {n:>8} {m:>10} {w:>10}")


if __name__ == "__main__":
    main()
