## MDD-based sizing / losing-streak throttle (2026-08-20)

Wired §4's documented-but-untested rules into the equity simulation: script `simulate_mdd_sizing_2020_2026.py` (copy of `simulate_equity_curve_2020_2026.py`, same panel/entry-signal/exit rule). Added: portfolio drawdown from peak > 15% -> cut position sizing to 3% and halt new entries until equity recovers within 5% of the prior peak; 5 consecutive losing closes -> halt new entries until the next winning close (existing open positions keep running under their own exit rule).

| | Baseline (no throttle) | With MDD/loss-streak throttle |
|---|---|---|
| Final equity | 234,365 THB | 232,562 THB |
| CAGR | 14.02% | 13.88% |
| Max drawdown | **-47.1%** | **-15.9%** |
| Trades | 1,098 | 320 |
| Win rate | 25.6% | 30.0% |
| Avg gain / avg loss | +28.7% / -6.6% | +42.0% / -7.2% |
| Throttled/halted days | - | 1,029 MDD-throttled, 210 loss-streak-halted (of 1,575) |

**Interpretation:** near-free lunch. Max drawdown falls 3x (-47%->-16%) while CAGR gives up only 0.14pp and final equity only 0.8% (234,365->232,562 THB). The throttle worked by sitting out ~65% of trading days during the prolonged 2022-2025 bear/flat stretch - trade count fell 71% while win rate and average gain both improved, i.e. it cut off entries into a weak period rather than just adding noise. This is the highest-value single change tested against the process: §4's rules, previously just documented, measurably do what they're supposed to do. Same caveats as the baseline run apply (survivorship bias, no transaction costs, single in-sample period, synthesized trailing-stop exit) - this test only isolates the throttle's effect.
