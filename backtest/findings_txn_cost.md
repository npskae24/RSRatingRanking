## Transaction cost impact (2026-08-20)

Script `simulate_txn_cost_2020_2026.py` (copy of `simulate_equity_curve_2020_2026.py`, same panel/entry/exit/sizing) - added a round-trip cost model applied on every buy and sell: 0.1665%/side (0.15% commission + 0.005% SET trading fee + 0.001% clearing fee + 7% VAT on the commission portion; assumed typical online-retail rate, not a confirmed broker schedule - kept as one named constant `ROUNDTRIP_COST_PCT_PER_SIDE` for easy auditing/adjustment).

| | No cost | With cost |
|---|---|---|
| Final equity | 234,365 THB | 203,155 THB |
| CAGR | 14.02% | 11.55% |
| Max drawdown | -47.1% | -51.5% |
| Trades | 1,098 | 1,099 |
| Win rate | 25.6% | 25.7% |
| Total cost paid | - | ~29,700-31,200 THB |
| Edge over benchmark (10.44% CAGR) | +3.58pp | +1.11pp |

**Interpretation:** costs cut the strategy's edge over the passive benchmark by roughly two-thirds (3.58pp -> 1.11pp CAGR). 1,098 round trips compound a small 0.1665%/side fee into a ~2.5pp CAGR drag. Max drawdown also worsens slightly (-51.5% vs -47.1%) since costs bite hardest right when hard-stops are firing most. At this trade frequency the remaining edge over buy-and-hold is thin - a realistically higher rate (e.g. 0.25%/side, if the actual broker schedule turns out worse than assumed) would likely erase most or all of the remaining 1.11pp. Confirming actual brokerage rates, and reducing trade count (the MDD-throttle findings above cut trades 71% with almost no CAGR cost - a natural pairing with this finding), matters more than further signal tuning.

**Correction (2026-08-21): actual commission confirmed at 0.07%, not the 0.15% online-retail guess used above.** `ROUNDTRIP_COST_PCT_PER_SIDE` in `simulate_ultimate_2020_2026.py` (and everything downstream that imports it - the Try-3 survivorship scripts) updated from 0.1665% to **0.0809%/side** (0.07% commission + 0.005% SET trading fee + 0.001% clearing fee + 7% VAT on the commission portion only: `0.0007 + 0.00005 + 0.00001 + 0.07*0.0007 = 0.000809`). This file's own numbers above are NOT re-run with the corrected rate (they still isolate the txn-cost effect in isolation, at the old assumed rate, which is still directionally useful) - see `findings_survivorship_try3.md` for numbers that use the corrected 0.0809% rate. Note also: re-running `simulate_ultimate_2020_2026.py` at the LOWER corrected cost unexpectedly produced a WORSE final result (594,767->433,797 THB) than the higher old cost - see that finding's chaos-sensitivity caveat before treating any single cost-vs-cost comparison in this stacked simulation as a clean causal read.
