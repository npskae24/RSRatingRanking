## Survivorship bias quantification (2026-08-20)

Script `survivorship_check.py` - compares today's 867-ticker universe (`backup/close_price.csv` columns) against the oldest available snapshot (2022-10-19, 777 tickers, from OneDrive `backup/*.xlsx`).

- **64 of 777 tickers (8.2%) present on 2022-10-19 are gone from today's universe** - delisted, suspended, or otherwise dropped. Examples: `24CS.BK`, `3K-BAT.BK`, `7UP.BK`, `ABICO.BK`, `ACAP.BK`, `ALL.BK`, `AQ.BK`, `BKI.BK`, `BPP.BK`, `BROOK.BK`.
- **154 tickers in today's universe didn't exist on 2022-10-19** - new listings since; correctly included in the backtest, not a bias.
- Overlap: 713/777 = 91.8%.

**Lower bound, not the real number:** 2022-10-19 is already 2 years 9 months after the equity simulation's 2020-01-02 start. Any name that delisted between 2020 and late 2022 (a window that includes the COVID crash - a high-delisting-risk period) is invisible to this comparison too. The true gap for the full 2020-2026 backtest window is larger than 8.2%.

**Interpretation:** 8.2%+ of the historical universe is silently missing from the 234,365 THB equity result, and a momentum/breakout strategy specifically would have bought into some of these names before suspension/delisting - those would show up as forced losses (SP/NP freezes capital, delisting can be a near-total loss) that never touch the simulation. Read the simulation's CAGR and drawdown as an upper bound; the gap is plausibly meaningful (8%+ minimum universe turnover in under half the backtested window), not just a rounding-error caveat.
