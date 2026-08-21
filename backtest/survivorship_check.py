"""
Quantifies (a lower bound on) survivorship bias in the 2020-2026 equity
simulation, which used today's 867-ticker universe for the whole backtest
period. Compares today's universe against the earliest available snapshot
(2022-10-19) - itself already 2+ years after the 2020-01-02 simulation start,
so any gap found here understates the true bias for the full window.
"""
import glob
import pandas as pd

CURRENT_CLOSE_CSV = "D:/Stocktrading/RSRatingRanking-master/backup/close_price.csv"
OLDEST_SNAPSHOT_GLOB = "C:/Users/PongsakornNivesvivat/OneDrive/STOCKTRADING/RSRatingRanking-master/backup/20221019_*.xlsx"


def main():
    current = set(pd.read_csv(CURRENT_CLOSE_CSV, index_col=0, nrows=1).columns)

    snapshot_file = sorted(glob.glob(OLDEST_SNAPSHOT_GLOB))[-1]  # latest timestamp that day = most complete
    df_old = pd.read_excel(snapshot_file)
    old = set(f"{s}" if str(s).endswith(".BK") else f"{s}.BK" for s in df_old["SecCode"].dropna().unique())

    disappeared = sorted(old - current)
    new_listings = sorted(current - old)
    overlap = old & current

    print(f"Snapshot file: {snapshot_file}")
    print(f"2022-10-19 universe: {len(old)} tickers")
    print(f"Current universe:    {len(current)} tickers")
    print(f"Overlap:              {len(overlap)} tickers ({len(overlap)/len(old)*100:.1f}% of 2022-10-19 universe still present)")
    print(f"Disappeared (in 2022-10-19, NOT in current): {len(disappeared)}")
    print(f"  examples: {disappeared[:10]}")
    print(f"New listings (in current, NOT in 2022-10-19): {len(new_listings)}")
    print(f"  examples: {new_listings[:10]}")


if __name__ == "__main__":
    main()
