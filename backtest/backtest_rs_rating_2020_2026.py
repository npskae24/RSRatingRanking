"""
RS Rating backtest, 2020-01-01 to 2026-06-30, computed directly from yfinance
historical prices (not from sparse xlsx snapshots, which only start 2022-10-19).

Caveat: uses the CURRENT SET stock universe (backup/close_price.csv columns) as
the ticker list for the whole period -> survivorship bias. Delisted stocks from
2020-2022 are not included; recently-listed stocks just get NaN RS Rating until
they have 252 trading days of price history.
"""
import os
import pandas as pd
import numpy as np
import yfinance

HERE = os.path.dirname(__file__)
TICKER_SOURCE = os.path.join(HERE, "..", "backup", "close_price.csv")
PRICE_CACHE = os.path.join(HERE, "price_cache_2018_2026.csv")
VOLUME_CACHE = os.path.join(HERE, "volume_cache_2018_2026.csv")
OUT_CSV = os.path.join(HERE, "rs_backtest_longform_2020_2026.csv")

PERIODS = [63, 126, 189, 252]      # trading days, same as stock_ranking.py
WEIGHTS = [0.4, 0.2, 0.2, 0.2]
HORIZONS = [14, 28, 60, 90, 120, 180]  # calendar days
TOLERANCE = 10

DOWNLOAD_START = "2018-10-01"   # buffer before 2020 for the 252d lookback
OBSERVE_START = pd.Timestamp("2020-01-01")
OBSERVE_END = pd.Timestamp("2026-06-30")


def get_tickers():
    df = pd.read_csv(TICKER_SOURCE, index_col=0, nrows=1)
    return list(df.columns)


def download_prices(tickers):
    if os.path.isfile(PRICE_CACHE):
        print(f"Loading cached price panel from {PRICE_CACHE}")
        df_prices = pd.read_csv(PRICE_CACHE, index_col=0, parse_dates=True)
        df_volume = pd.read_csv(VOLUME_CACHE, index_col=0, parse_dates=True) if os.path.isfile(VOLUME_CACHE) else None
        return df_prices, df_volume

    print(f"Downloading {len(tickers)} tickers from {DOWNLOAD_START} to latest via yfinance...")
    # auto_adjust defaults to True (adjusted Close) - must match the live pipeline's own
    # yfinance.download() call, and must be adjusted or every split/dividend reads as a price crash.
    raw = yfinance.download(tickers, start=DOWNLOAD_START, threads=True)
    df_prices = raw["Close"].dropna(axis=1, how="all")
    df_volume = raw["Volume"].reindex(columns=df_prices.columns)
    df_prices = df_prices.sort_index()
    df_volume = df_volume.reindex(df_prices.index)

    n_crash_days = (df_prices.pct_change() < -0.4).sum().sum()
    print(f"Coverage: {df_prices.shape[1]}/{len(tickers)} tickers downloaded. "
          f"Single-day drops < -40% across panel: {n_crash_days} (sanity check for unadjusted-price contamination).")
    per_year_coverage = df_prices.notna().groupby(df_prices.index.year).sum().max(axis=1)
    print(f"Max non-NaN tickers per year:\n{per_year_coverage}")

    df_prices.to_csv(PRICE_CACHE)
    df_volume.to_csv(VOLUME_CACHE)
    print(f"Price panel: {df_prices.shape}, range {df_prices.index.min()} to {df_prices.index.max()}")
    return df_prices, df_volume


def compute_rs_rank(df_prices):
    df_returns = pd.DataFrame(
        index=df_prices.index,
        columns=pd.MultiIndex.from_product([df_prices.columns, PERIODS], names=["SecCode", "Period"]),
        dtype=float,
    )
    for p in PERIODS:
        shifted = df_prices.shift(p)
        df_returns.loc[:, (slice(None), p)] = ((df_prices - shifted) / shifted).values

    weights_s = pd.Series(WEIGHTS, index=PERIODS)
    df_rs = (
        df_returns.stack(level=0, dropna=False)
        .mul(weights_s, axis=1)
        .sum(axis=1, min_count=1)
        .unstack(level=1)
    )
    return df_rs.rank(axis=1, pct=True)


def forward_return_panel(df_prices, observe_dates, horizon_days):
    idx = df_prices.index
    targets = []
    for d in observe_dates:
        target = d + pd.Timedelta(days=horizon_days)
        window = idx[(idx >= target) & (idx <= target + pd.Timedelta(days=TOLERANCE))]
        targets.append(window[0] if len(window) else pd.NaT)
    target_s = pd.Series(targets, index=observe_dates)

    df_base = df_prices.reindex(observe_dates)
    df_target = pd.DataFrame(index=observe_dates, columns=df_prices.columns, dtype=float)
    valid = target_s.notna()
    df_target.loc[valid] = df_prices.reindex(target_s[valid].values).values
    return df_target / df_base - 1


def main():
    tickers = get_tickers()
    df_prices, df_volume = download_prices(tickers)

    df_rs_rank = compute_rs_rank(df_prices)
    observe_dates = df_rs_rank.index[(df_rs_rank.index >= OBSERVE_START) & (df_rs_rank.index <= OBSERVE_END)]
    # ponytail: sample every 5th trading day (~weekly) - a 180d horizon otherwise reuses each
    # stock's return ~180x across consecutive daily rows, inflating n without adding information.
    observe_dates = observe_dates[::5]
    df_rs_rank = df_rs_rank.loc[observe_dates]
    print(f"RS panel (observe window): {df_rs_rank.shape}, {observe_dates.min()} to {observe_dates.max()}")

    long_df = df_rs_rank.stack().rename("rs_rating").reset_index()
    long_df.columns = ["date", "symbol", "rs_rating"]
    print(f"Long-form RS observations: {len(long_df)}")

    long_df["decile"] = long_df.groupby("date")["rs_rating"].transform(
        lambda s: pd.qcut(s, 10, labels=False, duplicates="drop") if s.nunique() >= 10 else np.nan
    )
    long_df["top20"] = long_df["rs_rating"] >= long_df.groupby("date")["rs_rating"].transform(lambda s: s.quantile(0.8))

    for h in HORIZONS:
        col = f"fwd_{h}d"
        fwd_panel = forward_return_panel(df_prices, observe_dates, h)
        fwd_long = fwd_panel.stack().rename(col).reset_index()
        fwd_long.columns = ["date", "symbol", col]
        long_df = long_df.merge(fwd_long, on=["date", "symbol"], how="left")
        print(f"  computed {col}: {long_df[col].notna().sum()} non-null")

    long_df.to_csv(OUT_CSV, index=False)
    print(f"Saved {OUT_CSV}")

    print("\n=== Decile table (mean fwd return, win rate) ===")
    for h in HORIZONS:
        col = f"fwd_{h}d"
        g = long_df.dropna(subset=[col, "decile"]).groupby("decile")[col]
        print(f"\n-- Horizon {h}d --")
        print(g.agg(n="count", mean="mean", winrate=lambda s: (s > 0).mean()))

    print("\n=== Top20% (RS>=80th pct that day) vs Rest ===")
    for h in HORIZONS:
        col = f"fwd_{h}d"
        g = long_df.dropna(subset=[col]).groupby("top20")[col]
        print(f"\n-- Horizon {h}d --")
        print(g.agg(n="count", mean="mean", winrate=lambda s: (s > 0).mean()))


if __name__ == "__main__":
    main()
