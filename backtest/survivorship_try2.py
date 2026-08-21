"""
Try 2 of the survivorship-bias test (per addendum's Try-1 follow-up,
2026-08-21). Try 1 (`simulate_survivorship_2020_2026.py`) could only measure
14/98 `exclusion_list.txt` names because yfinance has nothing for the rest.
This uses the OneDrive `backup/*.xlsx` snapshots (2022-10-19 onward, one file
per script run, SecCode/RS Rating (raw)/RS Score (percentile)/Close Price
columns, no volume) to find names that existed in the live universe back
then and are gone from today's 867-ticker universe but were NOT already
covered by Try 1 - especially checking the 21 tickers yfinance returned zero
data for (GL.BK named specifically in the addendum's Try-1 write-up).

No volume in this data, so the full TightBase/BreakoutVolumeConfirmed/score
formula can't be replicated - this is an existence + RS-percentile-trajectory
check, not a P&L simulation. Purpose: for each newly-found gone ticker, see
whether it was ever RS>=80pct (the entry gate) shortly before vanishing, and
what its price did right before the snapshots stop - i.e. bound whether Try
1's "0 write-offs" result would plausibly have held up if these names could
have been included too.
"""
import os
import glob
import re
import pandas as pd

HERE = os.path.dirname(__file__)
REPO_ROOT = os.path.dirname(HERE)
ONEDRIVE_BACKUP = r"C:\Users\PongsakornNivesvivat\OneDrive\STOCKTRADING\RSRatingRanking-master\backup"
PRICE_CACHE = os.path.join(HERE, "price_cache_2018_2026.csv")
EXCLUSION_LIST = os.path.join(REPO_ROOT, "exclusion_list.txt")

TRY1_MEASURED = {
    "PRO.BK", "F&D.BK", "BLISS.BK", "POLAR.BK", "GSTEEL.BK", "FUTUREPF.BK",
    "PPF.BK", "ERWPF.BK", "BKKCP.BK", "CPTGF.BK", "URBNPF.BK", "SIRIP.BK",
    "S&J.BK", "NOK.BK",
}
TRY1_NO_DATA = {
    "THL.BK", "IFEC.BK", "PAE.BK", "TSF.BK", "SAFARI.BK", "WORLD.BK",
    "POMPUI.BK", "APEX.BK", "GL.BK", "PACE.BK", "PE.BK", "MIT.BK",
    "SHREIT.BK", "HREIT.BK", "ABPIF.BK", "3K-BAT.BK", "SFP.BK", "SSS.BK",
    "TCCC.BK", "MACO.BK", "WELL.BK",
}


def pick_one_file_per_date(files):
    by_date = {}
    for f in files:
        m = re.match(r"(\d{8})_", os.path.basename(f))
        if not m:
            continue
        date = m.group(1)
        by_date.setdefault(date, f)  # first one seen for that date wins
    return by_date


def main():
    files = glob.glob(os.path.join(ONEDRIVE_BACKUP, "*.xlsx"))
    by_date = pick_one_file_per_date(files)
    print(f"{len(files)} snapshot files -> {len(by_date)} unique dates, "
          f"{min(by_date)} to {max(by_date)}")

    today_universe = set(pd.read_csv(PRICE_CACHE, index_col=0, nrows=0).columns)
    with open(EXCLUSION_LIST) as f:
        exclusion_set = {line.strip() for line in f if line.strip()}

    records = []
    for date_str in sorted(by_date):
        path = by_date[date_str]
        try:
            df = pd.read_excel(path, usecols=["SecCode", "RS Score", "Close Price"])
        except Exception as e:
            print(f"  skip {path}: {e}")
            continue
        df["date"] = pd.to_datetime(date_str, format="%Y%m%d")
        records.append(df)

    all_df = pd.concat(records, ignore_index=True)
    print(f"Loaded {len(all_df)} rows across {all_df['date'].nunique()} dates, "
          f"{all_df['SecCode'].nunique()} distinct SecCodes")

    last_seen = all_df.groupby("SecCode")["date"].max()
    first_seen = all_df.groupby("SecCode")["date"].min()
    all_seen_tickers = set(last_seen.index)

    gone = all_seen_tickers - today_universe
    print(f"\n{len(gone)} tickers seen in OneDrive snapshots but absent from today's "
          f"{len(today_universe)}-ticker live universe")

    new_finds = gone - TRY1_MEASURED
    print(f"{len(new_finds)} of those NOT already covered by Try 1's 14 measured names")

    overlap_with_no_data = new_finds & TRY1_NO_DATA
    print(f"\n{len(overlap_with_no_data)} overlap with Try 1's 21 no-yfinance-data tickers: "
          f"{sorted(overlap_with_no_data)}")

    gl = all_df[all_df["SecCode"] == "GL.BK"].sort_values("date")
    print(f"\n=== GL.BK trajectory in OneDrive snapshots ({len(gl)} observations) ===")
    if len(gl):
        print(gl[["date", "RS Score", "Close Price"]].to_string(index=False))
        print(f"Max RS Score ever recorded: {gl['RS Score'].max():.3f} "
              f"(entry gate is >=0.80)")
    else:
        print("GL.BK never appears in any OneDrive snapshot (2022-10-19 onward) - "
              "already gone from the universe before this data starts.")

    print(f"\n=== Full detail: new-find gone tickers, last-seen date/price/RS Score ===")
    detail = pd.DataFrame({
        "last_seen": last_seen.loc[sorted(new_finds)],
        "first_seen": first_seen.loc[sorted(new_finds)],
        "in_exclusion_list": [t in exclusion_set for t in sorted(new_finds)],
    })
    last_rows = all_df.sort_values("date").groupby("SecCode").last()
    detail["last_rs_score"] = last_rows.loc[detail.index, "RS Score"]
    detail["last_close_price"] = last_rows.loc[detail.index, "Close Price"]
    max_rs = all_df.groupby("SecCode")["RS Score"].max()
    detail["max_rs_score_ever"] = max_rs.loc[detail.index]
    detail = detail.sort_values("last_seen")
    print(detail.to_string())
    detail.to_csv(os.path.join(HERE, "survivorship_try2_new_finds.csv"))


if __name__ == "__main__":
    main()
