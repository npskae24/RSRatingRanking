## Survivorship bias, Try 3: full production signal on 18 confirmed-delisted names + corrected txn cost + sizing sweep (2026-08-21)

Follow-up to `findings_survivorship_try2.md`, which could only proxy via RS Score (no volume, so the full entry signal couldn't be replicated for the 68 OneDrive-found gone tickers). This closes that gap for as many as still have yfinance data, and simultaneously applies a corrected transaction-cost assumption and sweeps initial position sizing.

### Transaction cost correction

`ROUNDTRIP_COST_PCT_PER_SIDE` in `simulate_ultimate_2020_2026.py` (the shared source all Try-1/2/3 survivorship scripts import from) updated from the earlier 0.15%-commission guess (0.1665%/side total) to the **actual confirmed rate: 0.07% commission**, giving **0.0809%/side** (0.07% + 0.005% SET fee + 0.001% clearing fee + 7% VAT on the commission portion only). See `findings_txn_cost.md`'s correction note.

### Coverage: 18 names now spliced with full OHLCV (up from Try 1's 14)

`download_try2_names.py` fetched yfinance data for Try 2's 68 OneDrive-found gone tickers. **Only 8/68 returned any data; of those, only 4 are genuinely delisted with a real cutoff** (`SLM.BK` 2024-10-29, `STHAI.BK` 2025-01-08, `ACAP.BK` 2026-03-09, `BPP.BK` 2026-08-11 — the other 4 (`KIAT.BK`, `IFS.BK`, `TRUE.BK`, `PSTC.BK`) still trade today, same false-positive pattern as Try 1's 64). Combined with Try 1's 14, **18 total genuinely-delisted names now spliced into the panel with full price+volume+low**, letting `simulate_survivorship_try3_2020_2026.py` run the exact production entry signal (RS>=80pct AND TightBase AND BreakoutVolumeConfirmed AND score>=75) instead of Try 2's RS-only proxy.

**The two confirmed real fraud cases (`JKN.BK`, `STARK.BK`) still have ZERO yfinance data anywhere — Yahoo has purged them entirely. They remain unmeasurable by any yfinance-based method; only OneDrive's RS-only proxy (Try 2) ever touched them, and even that couldn't run the real entry signal on them.**

### Results (all at corrected 0.0809%/side cost)

| Sizing | Final equity | CAGR | Max DD | Trades | Forced write-offs |
|---|---|---|---|---|---|
| 5% (production baseline) | 609,547 THB | 31.34% | -27.95% | 727 | 1 (`ERWPF.BK`, -100%) |
| **10%** (fresh-account decision, addendum "Live decision" section) | 671,436 THB | 33.27% | -20.83% | 701 | 0 |
| 12.5% | 603,978 THB | 31.16% | -21.14% | 681 | 0 |

For reference, the no-survivorship-splice baseline at the SAME corrected cost and 5% sizing: 433,797 THB, CAGR 24.77%, DD -19.39% (see chaos-sensitivity note below for why this is lower than the 5%-with-splice row above, despite having fewer loss opportunities, not more).

### Chaos-sensitivity finding (important, applies beyond this specific test)

Re-running `simulate_ultimate_2020_2026.py` (no delisted names, just the cost correction) went from 594,767 THB/30.86% CAGR (old 0.1665% cost) to **433,797 THB/24.77% CAGR at the LOWER 0.0809% cost** — final equity got WORSE despite cheaper fees, which should be mechanically impossible for a simple compounding effect. Root cause: this simulation's execution layer is built from discrete threshold rules (MDD throttle at -15% DD, loss-streak halt after 5 losses, NAV+2% escalation cushion) that are evaluated fresh each day from the exact equity value. A few basis points of cumulative fee difference is enough to flip which side of a threshold equity lands on for a given day (loss-streak-halted days jumped from a much lower count to 579 in the re-run), and that flip cascades into a completely different trade sequence for the rest of the 6.5-year window. Confirmed again in the sizing sweep above: 12.5% sizing (nominally more aggressive) produced BOTH lower CAGR and higher DD than 10% — a non-monotonic result inconsistent with a simple linear sizing effect.

**Read every CAGR/DD number in this document (and the earlier "everything combined" / "NAV+2% escalation" sections) as belonging to a wide plausible band (roughly 20-33% CAGR depending on which small parameter perturbation you pick), not as a precise point estimate.** This is a property of the stacked execution rules' path-dependence, separate from and additive to the survivorship-bias and transaction-cost caveats already documented — a third, independent reason not to trust any single run's exact figure.

### Net read

The write-off rate stays low (0 or 1 out of ~700 trades) even with 18 real delisted names spliced in and the correct production signal running — reinforcing Try 1's finding that the *measurable* survivorship cost is small. But the two names most likely to have mattered (`JKN.BK`, `STARK.BK`, both real fraud cases) are permanently unmeasurable via yfinance, and the chaos-sensitivity finding above means even the measured numbers shouldn't be read to two significant figures. Combined verdict for the live-trading takeaway: expect real CAGR meaningfully below the 30%+ headline figures - discount for (a) transaction costs (~2.5pp, quantified), (b) unmeasurable survivorship tail risk (unquantified, real, includes fraud-type blowups), and (c) general model fragility to small parameter choices (unquantified band, ~±5-10pp based on the swings seen here).

Scripts: `download_try2_names.py`, `simulate_survivorship_try3_2020_2026.py`, `simulate_survivorship_try3_size100_2020_2026.py`, `simulate_survivorship_try3_size125_2020_2026.py` (all new; output CSVs gitignored same as other backtest output).
