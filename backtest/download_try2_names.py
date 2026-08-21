"""
Try 3: pull full OHLCV (Close/Volume/Low, not just Close) for the 68 tickers
Try 2 found gone from today's universe but missing from Try 1's yfinance-based
set - closes the "no volume, RS-gate-only proxy" gap flagged in
findings_survivorship_try2.md. Same download pattern as download_delisted.py.
"""
import os
import datetime
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(__file__)
NEW_FINDS_CSV = os.path.join(HERE, "survivorship_try2_new_finds.csv")
OUT_PRICE = os.path.join(HERE, "try2_price_cache.csv")
OUT_VOLUME = os.path.join(HERE, "try2_volume_cache.csv")
OUT_LOW = os.path.join(HERE, "try2_low_cache.csv")

START = datetime.date(2018, 1, 1)
END = datetime.date(2026, 8, 21)


def main():
    tickers = pd.read_csv(NEW_FINDS_CSV, index_col=0).index.tolist()
    print(f"{len(tickers)} tickers to fetch")

    data = yf.download(tickers, start=START, end=END, group_by="ticker",
                        auto_adjust=False, threads=True, progress=False)

    close_cols, vol_cols, low_cols = {}, {}, {}
    got, empty = [], []
    for t in tickers:
        try:
            sub = data[t]
        except KeyError:
            empty.append(t)
            continue
        close = sub["Close"].dropna()
        if close.empty:
            empty.append(t)
            continue
        got.append(t)
        close_cols[t] = sub["Close"]
        vol_cols[t] = sub["Volume"]
        low_cols[t] = sub["Low"]

    print(f"Got data for {len(got)}/{len(tickers)} tickers")
    print(f"No data at all for {len(empty)}: {empty}")

    close_df = pd.DataFrame(close_cols)
    vol_df = pd.DataFrame(vol_cols)
    low_df = pd.DataFrame(low_cols)
    close_df.to_csv(OUT_PRICE)
    vol_df.to_csv(OUT_VOLUME)
    low_df.to_csv(OUT_LOW)
    print(f"Saved to {OUT_PRICE}, {OUT_VOLUME}, {OUT_LOW}")

    last_valid = close_df.apply(lambda s: s.last_valid_index())
    print("\nLast valid trading date per ticker:")
    print(last_valid.sort_values().to_string())


if __name__ == "__main__":
    main()
