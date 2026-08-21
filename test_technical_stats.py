import numpy as np
import pandas as pd

# Constants from stock_ranking.py
BASE_LOOKBACK = 20
BASE_TIGHTNESS_MAX = 0.15
BREAKOUT_LOOKBACK = 20
VOLUME_AVG_WINDOW = 50
BREAKOUT_VOLUME_MULT = 1.5
MARKET_TREND_WINDOW = 50

def test_tight_base():
    # 70 daily rows
    dates = pd.date_range('2023-01-01', periods=70, freq='D')
    
    # NARROW.BK: price flat at 100, tightness will be 0.0 (<= 0.15)
    # WIDE.BK: price increases from 50 to 150, max is ~150, min ~120 in last 20 days.
    # tightness = (150-120)/120 = 30/120 = 0.25 (> 0.15)
    df_prices = pd.DataFrame(index=dates, data={
        'NARROW.BK': [100.0] * 70,
        'WIDE.BK': np.linspace(50, 150, 70)
    })
    
    # Code under test
    df_high_n = df_prices.rolling(BASE_LOOKBACK).max()
    df_low_n = df_prices.rolling(BASE_LOOKBACK).min()
    df_tight_base = ((df_high_n - df_low_n) / df_low_n) <= BASE_TIGHTNESS_MAX
    
    latest_date_ts = dates[-1]
    res = df_tight_base.loc[latest_date_ts]
    
    assert res['NARROW.BK'] == True, "Expected TightBase True for narrow range"
    assert res['WIDE.BK'] == False, "Expected TightBase False for wide range"
    print("PASS: test_tight_base")

def test_breakout_volume_confirmed():
    # 70 daily rows
    dates = pd.date_range('2023-01-01', periods=70, freq='D')
    
    # Prices: flat at 100 for 69 days, then breakout to 110 on day 70.
    prices_conf = [100.0] * 69 + [110.0]
    prices_unconf = [100.0] * 69 + [110.0]
    
    # Volume: 1000 per day for 69 days. Day 70: CONFIRMED=1600 (1.6x avg), UNCONFIRMED=1000 (1.0x avg)
    vol_conf = [1000.0] * 69 + [1600.0]
    vol_unconf = [1000.0] * 69 + [1000.0]
    
    df_prices = pd.DataFrame(index=dates, data={
        'CONFIRMED.BK': prices_conf,
        'UNCONFIRMED.BK': prices_unconf
    })
    df_volume = pd.DataFrame(index=dates, data={
        'CONFIRMED.BK': vol_conf,
        'UNCONFIRMED.BK': vol_unconf
    })
    
    # Code under test
    df_prior_high = df_prices.shift(1).rolling(BREAKOUT_LOOKBACK).max()
    df_vol_ratio = df_volume / df_volume.rolling(VOLUME_AVG_WINDOW).mean().replace(0, np.nan)
    df_breakout = (df_prices > df_prior_high) & (df_vol_ratio >= BREAKOUT_VOLUME_MULT)
    
    latest_date_ts = dates[-1]
    res = df_breakout.loc[latest_date_ts]
    
    assert res['CONFIRMED.BK'] == True, f"Expected BreakoutVolumeConfirmed True when volume ratio is {vol_conf[-1]/1000.0}"
    assert res['UNCONFIRMED.BK'] == False, f"Expected BreakoutVolumeConfirmed False when volume ratio is {vol_unconf[-1]/1000.0}"
    print("PASS: test_breakout_volume_confirmed")

def test_volume_ratio_nan():
    # 70 daily rows
    dates = pd.date_range('2023-01-01', periods=70, freq='D')
    
    # ZERO.BK: volume is 0 for the entire 70 days.
    df_volume = pd.DataFrame(index=dates, data={
        'ZERO.BK': [0.0] * 70
    })
    
    # Code under test
    df_vol_ratio = df_volume / df_volume.rolling(VOLUME_AVG_WINDOW).mean().replace(0, np.nan)
    
    latest_date_ts = dates[-1]
    res = df_vol_ratio.loc[latest_date_ts]
    
    assert pd.isna(res['ZERO.BK']), "Expected VolumeRatio NaN for 0 volume (preventing inf/crash)"
    print("PASS: test_volume_ratio_nan")

def test_market_regime_up():
    # 70 daily rows
    dates = pd.date_range('2023-01-01', periods=70, freq='D')
    
    # Uptrending panel
    prices_up1 = np.linspace(100, 200, 70)
    prices_up2 = np.linspace(50, 150, 70)
    df_prices_up = pd.DataFrame(index=dates, data={'A.BK': prices_up1, 'B.BK': prices_up2})
    
    # Downtrending panel
    prices_dn1 = np.linspace(200, 100, 70)
    prices_dn2 = np.linspace(150, 50, 70)
    df_prices_dn = pd.DataFrame(index=dates, data={'C.BK': prices_dn1, 'D.BK': prices_dn2})
    
    # Code under test for uptrend
    sr_market_index_up = (1 + df_prices_up.pct_change(fill_method=None).mean(axis=1).fillna(0)).cumprod()
    sr_market_regime_up_up = sr_market_index_up > sr_market_index_up.rolling(MARKET_TREND_WINDOW).mean()
    
    # Code under test for downtrend
    sr_market_index_dn = (1 + df_prices_dn.pct_change(fill_method=None).mean(axis=1).fillna(0)).cumprod()
    sr_market_regime_up_dn = sr_market_index_dn > sr_market_index_dn.rolling(MARKET_TREND_WINDOW).mean()
    
    latest_date_ts = dates[-1]
    assert sr_market_regime_up_up.loc[latest_date_ts] == True, "Expected MarketRegimeUp True for uptrending panel"
    assert sr_market_regime_up_dn.loc[latest_date_ts] == False, "Expected MarketRegimeUp False for downtrending panel"
    print("PASS: test_market_regime_up")

def test_sector_rs_nan_exclusion():
    # 70 daily rows
    dates = pd.date_range('2023-01-01', periods=70, freq='D')
    symbols = ['A.BK', 'B.BK', 'C.BK']
    
    # Fake RS ranks (between 0 and 1)
    df_rs_rank = pd.DataFrame(index=dates, data={
        'A.BK': np.random.uniform(0, 1, 70),
        'B.BK': np.random.uniform(0, 1, 70),
        'C.BK': np.random.uniform(0, 1, 70)
    })
    
    # Sector series matching what gets downloaded
    sr_stock_sector = pd.Series(index=symbols, data=['TECH', '-', 'nan'])
    
    # Code under test
    sr_stock_sector_classified = sr_stock_sector.replace(['-', 'nan'], np.nan)
    df_sector_rs = df_rs_rank.T.groupby(sr_stock_sector_classified).mean().T
    
    latest_date_ts = dates[-1]
    sector_rs_mapped = sr_stock_sector_classified.map(df_sector_rs.loc[latest_date_ts])
    
    assert 'TECH' in df_sector_rs.columns, "Expected 'TECH' sector to be present in grouped results"
    assert 'nan' not in df_sector_rs.columns, "Expected literal 'nan' sector to be excluded from grouped results"
    assert '-' not in df_sector_rs.columns, "Expected literal '-' sector to be excluded from grouped results"
    
    assert pd.notna(sector_rs_mapped['A.BK']), "Expected valid SectorRS for classified TECH sector"
    assert pd.isna(sector_rs_mapped['B.BK']), "Expected NaN SectorRS for '-' sector"
    assert pd.isna(sector_rs_mapped['C.BK']), "Expected NaN SectorRS for 'nan' sector"
    print("PASS: test_sector_rs_nan_exclusion")

def main():
    print("Running synthetic pandas technical signal tests...")
    tests = [
        test_tight_base,
        test_breakout_volume_confirmed,
        test_volume_ratio_nan,
        test_market_regime_up,
        test_sector_rs_nan_exclusion
    ]
    
    all_passed = True
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"FAIL: {t.__name__} - {e}")
            all_passed = False
        except Exception as e:
            print(f"ERROR: {t.__name__} - {e}")
            all_passed = False
            
    if all_passed:
        print("\nSUMMARY: All tests PASS")
    else:
        print("\nSUMMARY: Some tests FAIL")

if __name__ == '__main__':
    main()
