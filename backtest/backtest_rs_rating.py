import glob, os, re
import pandas as pd
import numpy as np

BACKUP = "C:/Users/PongsakornNivesvivat/OneDrive/STOCKTRADING/RSRatingRanking-master/backup"
CLOSE_CSV = f"{BACKUP}/close_price-PONGSAKORN-X1.csv"

RS_COL = "RS Rating (Type longest)"
HORIZONS = [14, 28, 60, 90, 120, 180]  # calendar days
TOLERANCE = 10  # max calendar days past target to accept a price match

def load_xlsx_snapshots():
    files = glob.glob(f"{BACKUP}/[0-9]*_*.xlsx")
    by_day = {}  # date -> (timestamp_str, path)
    for f in files:
        base = os.path.basename(f)
        m = re.match(r"(\d{8})_(\d{8})_(\d{6})\.xlsx", base)
        if not m:
            continue
        day = pd.to_datetime(m.group(1), format="%Y%m%d")
        ts = m.group(3)
        if day not in by_day or ts > by_day[day][0]:
            by_day[day] = (ts, f)
    print(f"Loaded {len(by_day)} unique snapshot days from {len(files)} files")

    rs_rows = {}
    close_rows = {}
    for i, (day, (ts, f)) in enumerate(sorted(by_day.items())):
        try:
            df = pd.read_excel(f)
        except Exception as e:
            print(f"skip {f}: {e}")
            continue
        if RS_COL not in df.columns or "SecCode" not in df.columns:
            continue
        df = df.dropna(subset=["SecCode"]).drop_duplicates(subset="SecCode", keep="last")
        rs_rows[day] = df.set_index("SecCode")[RS_COL]
        if "Close Price" in df.columns:
            close_rows[day] = df.set_index("SecCode")["Close Price"]
        if (i + 1) % 50 == 0:
            print(f"  parsed {i+1}/{len(by_day)}")

    rs_panel = pd.DataFrame(rs_rows).T.sort_index()
    xlsx_price_panel = pd.DataFrame(close_rows).T.sort_index()
    return rs_panel, xlsx_price_panel


def load_csv_price_panel():
    df = pd.read_csv(CLOSE_CSV, index_col=0)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def build_price_panel(xlsx_price_panel, csv_price_panel):
    combined = xlsx_price_panel.combine_first(csv_price_panel)
    return combined.sort_index()


def forward_return(price_panel, date, symbol, horizon_days):
    target = date + pd.Timedelta(days=horizon_days)
    future_dates = price_panel.index[(price_panel.index >= target) & (price_panel.index <= target + pd.Timedelta(days=TOLERANCE))]
    if len(future_dates) == 0:
        return np.nan
    tgt_date = future_dates[0]
    p0 = price_panel.at[date, symbol] if symbol in price_panel.columns and date in price_panel.index else np.nan
    p1 = price_panel.at[tgt_date, symbol] if symbol in price_panel.columns else np.nan
    if pd.isna(p0) or pd.isna(p1) or p0 == 0:
        return np.nan
    return p1 / p0 - 1


def main():
    rs_panel, xlsx_price_panel = load_xlsx_snapshots()
    csv_price_panel = load_csv_price_panel()
    price_panel = build_price_panel(xlsx_price_panel, csv_price_panel)

    print(f"RS panel: {rs_panel.shape}, price panel: {price_panel.shape}")
    print(f"RS panel date range: {rs_panel.index.min()} to {rs_panel.index.max()}")
    print(f"Price panel date range: {price_panel.index.min()} to {price_panel.index.max()}")

    # long-form: one row per (date, symbol) with RS rating
    long_rows = []
    for date in rs_panel.index:
        row = rs_panel.loc[date].dropna()
        for symbol, rs in row.items():
            long_rows.append((date, symbol, rs))
    long_df = pd.DataFrame(long_rows, columns=["date", "symbol", "rs_rating"])
    print(f"Long-form RS observations: {len(long_df)}")

    # decile bucket per date (cross-sectional rank within that day's universe)
    long_df["decile"] = long_df.groupby("date")["rs_rating"].transform(
        lambda s: pd.qcut(s, 10, labels=False, duplicates="drop") if s.nunique() >= 10 else np.nan
    )
    long_df["top20"] = long_df["rs_rating"] >= long_df.groupby("date")["rs_rating"].transform(lambda s: s.quantile(0.8))

    for h in HORIZONS:
        col = f"fwd_{h}d"
        vals = []
        pset = set(price_panel.columns)
        sub_dates = long_df["date"].unique()
        # precompute per-date target lookups for speed
        date_target_cache = {}
        for d in sub_dates:
            target = d + pd.Timedelta(days=h)
            fut = price_panel.index[(price_panel.index >= target) & (price_panel.index <= target + pd.Timedelta(days=TOLERANCE))]
            date_target_cache[d] = fut[0] if len(fut) else None

        def calc(row):
            tgt_date = date_target_cache.get(row["date"])
            sym = row["symbol"]
            if tgt_date is None or sym not in pset or row["date"] not in price_panel.index:
                return np.nan
            p0 = price_panel.at[row["date"], sym]
            p1 = price_panel.at[tgt_date, sym]
            if pd.isna(p0) or pd.isna(p1) or p0 == 0:
                return np.nan
            return p1 / p0 - 1

        long_df[col] = long_df.apply(calc, axis=1)
        print(f"  computed {col}: {long_df[col].notna().sum()} non-null")

    long_df.to_csv(os.path.join(os.path.dirname(__file__), "rs_backtest_longform.csv"), index=False)

    print("\n=== Decile table (mean fwd return, win rate) ===")
    for h in HORIZONS:
        col = f"fwd_{h}d"
        g = long_df.dropna(subset=[col, "decile"]).groupby("decile")[col]
        summary = g.agg(n="count", mean="mean", winrate=lambda s: (s > 0).mean())
        print(f"\n-- Horizon {h}d --")
        print(summary)

    print("\n=== Top20% (RS>=80th pct that day) vs Rest ===")
    for h in HORIZONS:
        col = f"fwd_{h}d"
        g = long_df.dropna(subset=[col]).groupby("top20")[col]
        summary = g.agg(n="count", mean="mean", winrate=lambda s: (s > 0).mean())
        print(f"\n-- Horizon {h}d --")
        print(summary)


if __name__ == "__main__":
    main()
