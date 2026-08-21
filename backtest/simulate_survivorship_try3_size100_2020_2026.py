"""
Same as simulate_survivorship_try3_2020_2026.py (18 delisted names spliced
in, corrected 0.0809%/side txn cost) but with POSITION_SIZE_PCT raised from
the 5% baseline to 10% - the fresh-account (DD=0) initial sizing decided in
the addendum's "Live decision" section (2026-08-21), never previously run
through any backtest. Thin driver: monkey-patches the constant on the
already-written try3 module rather than duplicating its ~290 lines (Python
resolves globals against the module's __dict__ at call time, so reassigning
the attribute after import changes what simulate() actually uses).
"""
import simulate_survivorship_try3_2020_2026 as base

base.POSITION_SIZE_PCT = 0.10
base.EQUITY_CSV = base.EQUITY_CSV.replace("try3_2020", "try3_size100_2020")
base.TRADE_LOG_CSV = base.TRADE_LOG_CSV.replace("try3_2020", "try3_size100_2020")

if __name__ == "__main__":
    print(f"POSITION_SIZE_PCT overridden to {base.POSITION_SIZE_PCT:.0%}")
    base.main()
