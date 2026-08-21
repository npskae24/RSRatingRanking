## Exit rule comparison: 2R/3R/5R scale-out vs trailing-50MA (2026-08-20)

Script `simulate_2r3r5r_exit_2020_2026.py` (copy of `simulate_equity_curve_2020_2026.py`, same panel/entry-signal/sizing) - exit replaced with the current documented practice: R = the -8% hard-stop distance from entry; sell 1/3 of the position at entry*(1+2R), 1/3 at entry*(1+3R), final 1/3 at entry*(1+5R), hard stop active on any unsold remainder.

| | 2R/3R/5R (current practice) | Trailing-50MA (prior sim) | Benchmark (buy&hold) |
|---|---|---|---|
| Final equity | 174,131 THB | 234,365 THB | 190,556 THB |
| CAGR | 8.92% | 14.02% | 10.44% |
| Max drawdown | **-14.1%** | -47.1% | -41.0% |
| Win rate | **57.6%** | 25.6% | - |
| Avg gain/loss | +29.7% / -10.2% | +28.7% / -6.6% | - |
| Exits | 706 (299 hard_stop, 170/135/102 at 2R/3R/5R) | 1,098 | - |

**Interpretation:** neither is strictly better - it's a risk-tolerance tradeoff. 2R/3R/5R is far safer (-14% DD vs -47%) and wins more often (57.6% vs 25.6%), but caps upside hard enough that it doesn't even beat passive buy-and-hold (174k vs 190k) - fixed profit targets sell winners into the extended trend moves the trailing exit captures. Trailing-50MA earns 34% more final equity but only by tolerating a drawdown 3x+ deeper. Given the stated shift toward mid/long-term position trading, trailing fits that direction better - but only if a -47% DD is something you'd actually hold through with real capital, not just on a backtest chart. Worth testing 2R/3R/5R combined with the MDD-throttle from the sizing findings, since that pairing might keep 2R/3R/5R's safety while recovering some of trailing's upside. Same caveats as the baseline run apply (survivorship bias, no transaction costs, single in-sample run); this comparison isolates the exit-rule effect only, holding entry/sizing/universe constant.
