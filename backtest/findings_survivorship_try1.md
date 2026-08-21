## Survivorship bias, Try 1: splice known-delisted names back into the panel (2026-08-21)

Direct follow-up to `findings_survivorship.md` (which only quantified the gap, 8.2%+ minimum). This attempts to actually measure the CAGR/DD impact by re-running `simulate_ultimate_2020_2026.py`'s exact signal/scoring/sizing/exit logic against a panel with delisted names spliced back in.

**Method**: `download_delisted.py` pulls yfinance history for all 98 tickers in `exclusion_list.txt` (2018-01-01 to today). `simulate_survivorship_2020_2026.py` splices the result into the normal `price_cache_2018_2026.csv` panel and forces a full write-off (-100% return) on any position still open when its ticker's price data ends, instead of the silent freeze `simulate_ultimate_2020_2026.py` would otherwise do (`px.get(sym, entry_price)` fallback masks a missing price as "unchanged," not a loss).

**Coverage turned out much smaller than expected**:
- 78/98 tickers returned any data from yfinance.
- Of those 78, only **14 have a real data cutoff before today** (genuinely delisted/suspended) - the other **64 are still trading now**, just excluded from the live ranking universe for unrelated reasons (mostly REIT/property-fund tickers not covered by the SET listed-companies HTML scrape `stock_ranking.py` uses).
- **21/98 tickers returned zero data at all** - Yahoo has purged them entirely. Unmeasurable by this method.
- `exclusion_list.txt` (98 entries total, accumulated over this repo's history) covers far fewer delistings than `findings_survivorship.md`'s direct universe-snapshot comparison found (64 tickers gone in the 2022-2026 window alone) - this method under-samples the real delisting population, it does not bound it.

**Result, 14 genuinely-delisted names spliced in**:

| | `simulate_ultimate` baseline (594,767 THB) | + 14 delisted names spliced in |
|---|---|---|
| Final equity | 594,767 THB | 622,686 THB |
| CAGR | 30.86% | 31.76% |
| Max drawdown | -23.5% | -20.81% |
| Trades | 749 | 703 |
| Win rate | 33.8% | 34.1% |
| Forced delisting write-offs | - | **0** |

None of the 14 spliced-in names ever had an open position at the moment their data ended - the entry signal (RS>=80pct AND TightBase AND BreakoutVolumeConfirmed AND score>=75) never fired on them close enough to delisting to still be held. Numbers moved slightly in the GOOD direction (more candidates in the pool on some days), not bad - i.e. **this test found zero measured survivorship cost**, not a small one.

**Read this as "not measured," not "not present."** Three real gaps in what this test can see:
1. Half the 14 measured names are REIT/property funds (`PPF`, `ERWPF`, `FUTUREPF`, `CPTGF`, `URBNPF`) that delisted via fund restructuring/maturity, not financial distress - a low-probability signal-firing case to begin with, weak evidence either way.
2. The 21 tickers with zero Yahoo data are exactly the ones most likely to matter (total wipeouts sometimes get purged from Yahoo entirely) and are completely unmeasured here.
3. `exclusion_list.txt` itself only captures delistings the live pipeline happened to catch (a symbol that was matched once, then later failed to match) - it misses delistings from before this repo existed and any symbol that was never scraped in the first place. `GL.BK` (Group Lease PCL) is a concrete, known example: a real momentum darling for years before its 2018 governance/fraud scandal crashed the price ~90%+ in days - exactly the profile a RS/breakout strategy WOULD have bought beforehand, and it sits in the 21-ticker no-data bucket, invisible to this test.

**Mechanism worth noting**: the entry criteria (RS>=80pct + TightBase + volume-confirmed breakout) structurally excludes the "slow bleed into SP" profile - a stock heading toward suspension from prolonged financial distress is, almost by definition, failing RS and volume criteria long before the halt, so it's plausible the strategy self-selects away from that failure mode. That does NOT cover the "sudden blowup" profile (fraud/governance discovered overnight, GL.BK-style) - a stock can be a legitimate high-RS momentum name right up until the news breaks, and no technical-only signal sees that coming.

**Bottom line**: revise the "CAGR is inflated by survivorship bias" caveat from "unquantified but assume it matters" to "measured at 0% for the 14 names Yahoo still has data for, but the real gap is concentrated in ~21+ delisted names this method can't see at all (plus everything before `exclusion_list.txt` existed) - go to Try 2 (OneDrive `backup/*.xlsx` snapshots) to close that gap, particularly for pre-2022 delistings and any GL.BK-style sudden-collapse case."

Scripts: `download_delisted.py`, `simulate_survivorship_2020_2026.py` (both new, not checked in output CSVs - `delisted_*_cache.csv`, `equity_sim_*_survivorship_2020_2026.csv` gitignored same as other backtest output).
