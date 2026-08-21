"""
Same as simulate_survivorship_try3_size100_2020_2026.py but POSITION_SIZE_PCT
raised to 12.5% instead of 10% - the second sizing point requested alongside
the 10% fresh-account decision, to see how far the top-of-range aggressive
end pushes results.
"""
import simulate_survivorship_try3_2020_2026 as base

base.POSITION_SIZE_PCT = 0.125
base.EQUITY_CSV = base.EQUITY_CSV.replace("try3_2020", "try3_size125_2020")
base.TRADE_LOG_CSV = base.TRADE_LOG_CSV.replace("try3_2020", "try3_size125_2020")

if __name__ == "__main__":
    print(f"POSITION_SIZE_PCT overridden to {base.POSITION_SIZE_PCT:.1%}")
    base.main()
