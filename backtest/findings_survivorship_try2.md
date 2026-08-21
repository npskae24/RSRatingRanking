## Survivorship bias, Try 2: OneDrive snapshot existence + RS-gate check (2026-08-21)

Try 1 (`findings_survivorship_try1.md`) could only measure 14/98 `exclusion_list.txt` names via yfinance and found 0 impact - but flagged that as under-coverage, not evidence of no bias. This uses the OneDrive `RSRatingRanking-master/backup/*.xlsx` snapshots (265 files, deduped to 231 unique dates, 2022-10-19 to 2024-12-08, columns `SecCode`/`RS Score` (the percentile, not the raw score - see the repo's own `CLAUDE.md` column-swap note)/`Close Price`, no volume) to widen the net, per script `survivorship_try2.py`.

**Coverage widened a lot**: 893 distinct SecCodes appear across the snapshots. **69 are absent from today's 867-ticker live universe** - gone. **68 of those weren't among Try 1's 14 measured names at all** (only 5 overlap with Try 1's 21 no-yfinance-data list: `3K-BAT.BK`, `MACO.BK`, `SFP.BK`, `SSS.BK`, `TCCC.BK`). `GL.BK` (named in Try 1 as the concrete counter-example) never appears in any snapshot - already gone from the universe before this data starts in Oct 2022, so still unmeasured by either try.

**No volume in this data**, so the real production entry signal (RS>=80pct AND TightBase AND BreakoutVolumeConfirmed AND score>=75) can't be replicated. This is an RS-gate-only proxy: of the 68 newly-found gone tickers, **50 (74%) crossed `RS Score>=0.80` (the RS-only entry gate) at some point before vanishing from the snapshots.**

**Price change from that RS>=0.80 crossing to the last-seen price**, for those 50:
- Median: **-19.9%**
- 23/50 (46%) lost more than 20% from that point
- Worst cases: `SMK.BK` -99.4%, `PTECH.BK` -96.1%, `OTO.BK` -95.5%, `NUSA.BK` -80.2%, `NEWS.BK` -75.0%, `GSC.BK` -74.2%, `PSG.BK` -62.7%, `JKN.BK` -62.7%, `ACAP.BK` -62.5%
- A handful gained instead (`TRUE.BK` +129%, `SFP.BK` +228%, `24CS.BK` +96%) - some "gone" tickers left via merger/tender/name change at a premium, not distress; `TRUE.BK`'s case is the DTAC merger, a real example of "gone from the universe" that isn't a loss at all.

**Two named real-world cases in this list, both well-known SET incidents**: `JKN.BK` (JKN Global - 2023 accounting fraud / going-concern crisis) and `STARK.BK` (Stark Corp - 2023, one of Thailand's largest-ever accounting fraud cases, near-total loss). Both crossed the RS>=0.80 gate in this data. `STARK.BK`'s crossing is flagged as a likely proxy artifact, though (see caveats) - it happened at 0.02 THB, i.e. already-collapsed, not a "would have bought this on the way up" case.

**Caveats, all pushing toward this still being an underestimate of true bias, except where noted otherwise**:
1. **RS-only proxy likely overstates SOME hits, understates the true rate on others.** No TightBase/volume/liquidity gate here - some of these 50 would have failed the full production signal (illiquid penny names failing `AvgValue_20d` tiers), but conversely a plain RS-percentile screen can also spuriously spike for a near-worthless stock where tiny absolute moves are huge % swings (the likely explanation for `STARK.BK`'s crossing at 0.02 THB, already post-collapse) - net direction of the bias in the 74% figure is not resolved either way, treat it as a rough estimate not a precise rate.
2. **Right-censored at 2024-12-08** (the last OneDrive snapshot date) - many `last_seen` dates cluster exactly there, meaning "still present in the final snapshot we have," not confirmed still-gone or already-delisted after that date. True outcome (further crash, delisting, or recovery) for those names is unknown past this window.
3. **Still no P&L simulation** - this quantifies "the RS gate would plausibly have let the strategy in, and price fell hard afterward," not actual position sizing/exit-rule-adjusted loss. Can't be folded into the CAGR/DD numbers directly the way Try 1's forced-write-off mechanism could.
4. **`GL.BK` still unmeasured** - pre-dates this snapshot window too (starts Oct 2022, GL.BK's scandal was 2018).

**Bottom line**: Try 1's "0 measured survivorship impact" reads very differently now - it was a narrow-sample artifact (a small measured set dominated by REIT/fund conversions unrelated to distress), not evidence the risk is small. Try 2's much wider net (68 vs 14 names) shows the RS-gate-crossing-then-crashing pattern is common (74% of newly-found gone names) and sometimes severe (median -20%, worst cases near-total loss), including two confirmed real fraud cases (`JKN.BK`, `STARK.BK`). Treat the survivorship-bias caveat on the 30%+ CAGR figures as MATERIAL, not a minor footnote - probably a larger drag than the already-quantified transaction-cost drag (findings_txn_cost.md: -2.5pp CAGR), though this pass still can't put an exact number on it (no volume data blocks a real P&L re-run).

**If closing this further matters**: would need (a) volume history for these 68 names to run the actual production signal instead of the RS-only proxy, and (b) snapshot/price data past 2024-12-08 and pre-Oct-2022 to un-censor the window and catch pre-2022 cases like `GL.BK`. Neither is available in this repo currently.

Script: `survivorship_try2.py` (new, output `survivorship_try2_new_finds.csv` gitignored same as other backtest output).
