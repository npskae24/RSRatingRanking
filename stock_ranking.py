import datetime
import os
import shutil
import sys
from typing import Literal

import numpy as np
import yfinance
import requests
import logging
import pandas as pd

from yahoo_finance_scraper import get_stock_statistics, HEADERS

from selenium.webdriver.chrome.webdriver import WebDriver as ChromeWebDriver
from selenium.webdriver.chrome.webdriver import Service
from selenium.webdriver.common.by import By
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

# %% Constants

# Const: Configurable
GLOBAL_START_DATE: datetime.date = datetime.date(2015, 1, 1)
FORWARD_FILL: Literal['longest', 'ffill', 'none'] = 'none'

RANKING_THRESHOLD:         float = 0.8
SKIP_NAME_DOWNLOAD:        bool = False  # Skip downloading stock names from SET exchange
SKIP_PRICE_DOWNLOAD:       bool = False  # Skip downloading price from Yahoo Finance
SKIP_TODAY_PRICE_DOWNLOAD: bool = True   # Skip downloading today price from alternative source.
SKIP_STOCK_STATISTICS:     bool = True   # Skip fundamentals stats download - Thai .BK fundamentals via
                                          # yfinance .info are too incomplete/unreliable to depend on;
                                          # the system is 100%-technical now (see Stats: Technical below).
SKIP_DATA_DUMP:            bool = False  # Skip downloaded price, calculated returns dump at the end of script
PRODUCE_WATCHLIST:         bool = True   # Producting watchlist_{date}.txt
DAILY_OPERATION:           bool = True   # Script only computes the daily data.
DAILY_FILLING_MODE: Literal['longest', 'ffill', 'none'] = 'longest'

N_PRICE_THRESHOLD_DATE:       int = 5  # if no of stock price is less than this on a day, that day is discarded.
N_PRICE_THRESHOLD_UNDERLYING: int = 3  # If a stock has less that this no. price, then it is dropped.

PERIODS:   list[int] = [63, 126, 189, 252]  # in bars/trading days
WEIGHTS: list[float] = [0.4, 0.2, 0.2, 0.2]

# Const: Technical pattern / regime detection (price+volume only, no fundamentals needed)
BASE_LOOKBACK:        int = 20    # trading days for tight-base / consolidation range
BASE_TIGHTNESS_MAX:   float = 0.15  # max (rolling high - rolling low)/low over BASE_LOOKBACK to flag "tight base"
BREAKOUT_LOOKBACK:    int = 20    # trading days for prior-high breakout check
VOLUME_AVG_WINDOW:    int = 50    # trading days for average-volume baseline
BREAKOUT_VOLUME_MULT: float = 1.5   # volume must exceed this multiple of its baseline to confirm breakout
MARKET_TREND_WINDOW:  int = 50    # trading days MA for market-regime trend (equal-weight SET proxy)

# Const: Required fundamental stats (yfinance Ticker.info field name -> friendly output column name)
REQUIRED_STATS_FUNDAMENTALS: dict[str, str] = {
    'fiftyTwoWeekHigh': '52wHigh',
    'marketCap': 'marketCap',
    'profitMargins': 'profitMargins',
    'returnOnEquity': 'ROE',
    'totalRevenue': 'totalRevenue',
    'netIncomeToCommon': 'netIncomeToCommon',
    'revenueGrowth': 'revenueGrowth',
    'earningsQuarterlyGrowth': 'earningGrowth',
}

# Const: Convenience
dt_script_start = datetime.datetime.now()
dt_script_start_str = dt_script_start.strftime("%Y%m%d_%H%M%S")

# Const: Connections
__SET_LIST_STOCKS_URL = r"https://www.set.or.th/dat/eod/listedcompany/static/listedCompanies_en_US.xls"
__CONNECTION_MAX_RETRIES: int = 3
SIAMCHART_PRICE_URL: str = "http://siamchart.com/stock/"
SIAMCHART_PRICE_DATE_XPATH: str = r'//*[@id="content_body"]/div/div[6]'
CHROME_WEBDRIVER_PATH: str = r"driver/chromedriver_v131.exe"
N_THREADS: int = 8

# Const: Directories
__DATA_DIR = "set_stock_list/"
__PRICE_DIR = 'backup/'
__LATEST_DOWNLOADED_PRICE_FULLPATH = f"{__PRICE_DIR}/close_price.csv"
__LATEST_DOWNLOADED_VOLUME_FULLPATH = f"{__PRICE_DIR}/volume.csv"
__LATEST_COMPUTED_RETURN_FULLPATH = f"{__PRICE_DIR}/return.csv"
__LATEST_STOCK_STATS_FULLPATH = f"{__PRICE_DIR}/stats_fundamentals.csv"
__SET_LIST_FILENAME_PREFIX = rf"{__DATA_DIR}listedCompanies_en_US"  # without .xlsx
__YEARLY_OUTPUT_DIRECTORY = "./yearly/"
__REQUIRED_DIRS = ['./log/', './backup/', './set_stock_list/']
__SIAMCHART_MISSING_FILE: str = "siamchart_missing_stocks.txt"

# Const: Logging
__LOGGING_CONSOLE_FORMATTER = logging.Formatter('%(name)s |%(levelname)9s: %(message)s')
__LOGGING_FILE_FORMATTER = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
__LOGGING_LEVEL = logging.INFO

# %% Prelude
# Initiate logger
lggr = logging.getLogger("RS Rating Ranking")
__stream_hdlr = logging.StreamHandler(sys.stdout)
__stream_hdlr.setFormatter(__LOGGING_CONSOLE_FORMATTER)
__stream_hdlr.setLevel(__LOGGING_LEVEL)

lggr.addHandler(__stream_hdlr)
lggr.setLevel(logging.DEBUG)  # Always the finest level

# Directory check
for _dir in __REQUIRED_DIRS:
    if not os.path.isdir(_dir):
        lggr.info(f"Creating directory {_dir}")
        os.mkdir(_dir)

__file_hdlr = logging.FileHandler(filename=f'./log/{dt_script_start_str}.log')
__file_hdlr.setFormatter(__LOGGING_FILE_FORMATTER)
__file_hdlr.setLevel(logging.DEBUG)  # Always at lowest level
lggr.addHandler(__file_hdlr)  # Adding file handler once we ensure the directory existence.


# %% Utility Functions
# noinspection PyPep8Naming
def download_SET_stock_names_html():
    stock_list_fetching_datetime = dt_script_start
    stock_list_filename = f"{__SET_LIST_FILENAME_PREFIX}.html"
    stock_list_filename_bckup = (f"{__SET_LIST_FILENAME_PREFIX}_"
                                 f"{stock_list_fetching_datetime.strftime('%Y%m%d_%H%M%S')}.html")
    success = False
    for i in range(__CONNECTION_MAX_RETRIES):
        try:
            lggr.info(f"Downloading stock names from SET website.")
            response = requests.get(url=__SET_LIST_STOCKS_URL, headers=HEADERS)
            if response.status_code == 200:  # Good
                with open(stock_list_filename, 'wb') as f:
                    f.write(response.content)
            success = True
            break
        except Exception as e:
            lggr.warning(f"Getting SET stock names attempt ({i+1},{__CONNECTION_MAX_RETRIES}): "
                         f"Connection failed with exception args {e.args}.")
    if not success:  # Cannot get price
        lggr.warning("Failed downloading the SET stock names. Exiting without download.")
    try:
        shutil.copyfile(src=stock_list_filename, dst=stock_list_filename_bckup)
    except Exception as e:
        lggr.warning(f"Backing up SET stock file "
                     f"from {stock_list_filename} "
                     f"to {stock_list_filename_bckup} failed with exception \n {e.args}")


# noinspection PyPep8Naming
def get_SET_stock_list() -> list[str]:
    _p = f"{__SET_LIST_FILENAME_PREFIX}.html"
    lggr.info(f"Fetching stock names from {_p}.")
    if os.path.isfile(_p):
        _t = pd.read_html(_p, header=1)[0]
    else:
        raise FileNotFoundError(f"File {_p} doesn't exist. "
                                f"You can download the stock names manually to mitigate this. "
                                f"The file must be saved as .html file at {_p}. "
                                f"Source URL = {__SET_LIST_STOCKS_URL}")

    return _t['Symbol'].astype(str).tolist()


# noinspection PyPep8Naming
def get_SET_stock_sectors() -> pd.Series:
    """Bare symbol -> Sector, reusing the same scraped SET listed-company table (has an Industry/Sector column)."""
    _p = f"{__SET_LIST_FILENAME_PREFIX}.html"
    _t = pd.read_html(_p, header=1)[0]
    return _t.set_index('Symbol')['Sector'].astype(str)


# noinspection PyPep8Naming
def get_holiday() -> list[datetime.date]:
    _filedir = f"{__DATA_DIR}/th_holidays.csv"
    _sr = pd.read_csv(_filedir, index_col=0, parse_dates=True, header=None)
    _l = _sr.index.max()
    # noinspection PyTypeChecker
    if pd.Timestamp(datetime.date.today()) > _sr.index.max():
        lggr.warning(f"Today {datetime.date.today()} is greater than the maximum stroed holiday {_l}. "
                     f"Please update the holiday file in {_filedir}")
    return _sr.index.values.astype('datetime64[D]').tolist()


def get_exclusion_list() -> list[str]:
    _filedir = "exclusion_list.txt"
    _excl_list = list()
    with open(_filedir, 'r') as f:
        for ln in f:
            _excl_list.append(ln.strip())
    return _excl_list


def download_siamchart_prices() -> tuple[datetime.date, pd.Series]:
    browser_options = Options()
    browser_options.headless = False
    chrome: ChromeWebDriver = Chrome(options=browser_options,
                                     service=Service(executable_path=CHROME_WEBDRIVER_PATH))
    chrome.get(SIAMCHART_PRICE_URL)

    list_df = pd.read_html(chrome.page_source)
    df_siamchart_price_dirty: pd.DataFrame = list_df[2]  # Locked at table 2

    # price_date_str_raw: str = chrome.find_element_by_xpath(r'//*[@id="content_body"]/div/div[6]').text
    price_date_str_raw: str = chrome.find_element(by=By.XPATH, value=SIAMCHART_PRICE_DATE_XPATH).text
    price_date = datetime.datetime.strptime(price_date_str_raw.split()[0], "%Y-%m-%d")

    sr_prices: pd.Series = df_siamchart_price_dirty.set_index('Name').drop(labels='Average', axis=0)['Last']
    chrome.close()
    return price_date.date(), sr_prices


# %% Main Script
if __name__ == '__main__':
    lggr.info("Script starting ..")
    if not SKIP_NAME_DOWNLOAD:
        download_SET_stock_names_html()
    stock_list = get_SET_stock_list()
    # stock_list = ['AOT', 'BBL', 'CPALL', 'DELTA', 'EA', 'FORTH', 'HANA', 'PSG', 'YGG', 'ZIGA', 'TH']  # For dev only
    exclusion_list = get_exclusion_list()
    for excl_s in exclusion_list:
        if '.BK' in excl_s:
            s = excl_s.replace('.BK', '')
        else:
            s = excl_s
        try:
            stock_list.remove(s)
            lggr.debug(f"Dropped stock {s} as specified in exclusion list.")
        except ValueError as e:
            pass  # Already not in the initial list
    holidays = get_holiday()
    n_stock = len(stock_list)

    # Resolving download arguments
    start_offset = int(max(PERIODS)) + 1 + 10  # n returns takes n+1 data points, another +5 for safety factor
    if DAILY_OPERATION:
        skip_download = False
        # skip_download = SKIP_PRICE_DOWNLOAD  # For overriding above line
        start_download_date = np.busday_offset(datetime.date.today(), offsets=-1 * start_offset,
                                               roll='backward', holidays=holidays)
        return_start_date = start_download_date
    else:
        skip_download = SKIP_PRICE_DOWNLOAD
        return_start_date = GLOBAL_START_DATE
        start_download_date = np.busday_offset(GLOBAL_START_DATE, offsets=-1 * start_offset,
                                               roll='backward', holidays=holidays)

    lggr.debug(f"Daily Operation Type = {'Daily' if DAILY_OPERATION else 'Repopulate'}. "
               f"Enable price downloading is {skip_download}, "
               f"Download Range = {start_download_date}, to latest")

    download_latest_price: bool = False
    if not skip_download:
        lggr.info("Start downloading stock prices from Yahoo Finance, "
                  f"from {start_download_date} to the latest available date.")
        df_downloaded_price = yfinance.download([f'{s}.BK' for s in stock_list],
                                                start=start_download_date.astype(datetime.date),
                                                threads=N_THREADS)
        # This is because yfinance module is a bit stupid. start and end parameters seem to be exclusive (open interval)
        # However, the function returns DataFrame with both start and end date but with no value.
        # We remove the end parameter (thus defaulting to 'now'), and add some safety factor to the start date.
        safety_filter = df_downloaded_price.index >= pd.Timestamp(start_download_date)
        df_mega_price: pd.DataFrame = df_downloaded_price.loc[safety_filter]

        df_prices: pd.DataFrame = (df_mega_price['Close']
                                   .sort_index()
                                   .dropna(axis=0, thresh=N_PRICE_THRESHOLD_DATE)
                                   .dropna(axis=1, thresh=N_PRICE_THRESHOLD_UNDERLYING))
        # Volume for chart-pattern detection (breakout confirmation) - same filtering as df_prices.
        df_volume: pd.DataFrame = df_mega_price['Volume'].reindex(index=df_prices.index, columns=df_prices.columns)

        # Can safely check with today() here cuz yf is always real-time due to end=None
        if (pd.Timestamp.today() not in df_prices.index) and not SKIP_TODAY_PRICE_DOWNLOAD:
            lggr.info(f"today() not in the yfinance downloaded price. "
                      f"Setting up script to download from siamchart.com.")
            download_latest_price = True
        # Check for underlying with no price
        dropped_underlying = df_mega_price['Close'].columns.difference(df_prices.columns)
        if len(dropped_underlying) != 0:
            lggr.info(f"Dropping the following {len(dropped_underlying):d} "
                      f"since they have no price at all: {sorted(list(dropped_underlying))}")

        # Check for date with insuficient stock price
        pd_dropped_dates = df_mega_price.index.difference(df_prices.index)
        dropped_dates = pd_dropped_dates.astype('datetime64[ns]').values.astype('datetime64[D]').tolist()
        problematic_underlying = [df_mega_price.loc[d, 'Close'].dropna() for d in pd_dropped_dates]
        # noinspection PyTypeChecker
        non_holiday_dropped_dates = sorted(list(set(dropped_dates).difference(holidays)))
        if len(non_holiday_dropped_dates) != 0:
            lggr.warning(f"Some of the following non-holiday has been dropped due to having less than "
                         f"{N_PRICE_THRESHOLD_DATE} stock prices on that day: {non_holiday_dropped_dates}")
    else:
        lggr.info(f"Loading the latest available price offline from {__LATEST_DOWNLOADED_PRICE_FULLPATH}.")
        df_prices_loaded = pd.read_csv(__LATEST_DOWNLOADED_PRICE_FULLPATH,
                                       index_col=0, parse_dates=True)
        df_prices = df_prices_loaded
        if os.path.isfile(__LATEST_DOWNLOADED_VOLUME_FULLPATH):
            df_volume = pd.read_csv(__LATEST_DOWNLOADED_VOLUME_FULLPATH, index_col=0, parse_dates=True)
        else:
            lggr.warning(f"{__LATEST_DOWNLOADED_VOLUME_FULLPATH} not found - "
                        f"breakout/volume pattern columns will be all-NaN this run.")
            df_volume = pd.DataFrame(index=df_prices.index, columns=df_prices.columns, dtype=float)

    # Recording price source for reference
    df_price_source = pd.DataFrame(index=df_prices.index,
                                   columns=df_prices.columns,
                                   data='yfinance' if not skip_download else 'local',
                                   dtype=str)

    # Stats: Price
    if download_latest_price:
        lggr.info(f"Using selenium to download latest prices from {SIAMCHART_PRICE_URL}")
        sc_date, sr_sc_prices = download_siamchart_prices()
        if sc_date != datetime.date.today():
            lggr.warning(f"Prices displayed on {SIAMCHART_PRICE_URL} might not be up to date "
                         f"(shown={sc_date}, today={datetime.date.today()}. This might be due to the script being "
                         f"executed prematurely during the day.")
        lggr.info(f"Appending/replacing latest price from {SIAMCHART_PRICE_URL} (date={sc_date}) to the df_prices.")
        sr_sc_prices.index = map(lambda _s: f"{_s}.BK", sr_sc_prices.index)

        missing_stock_price = df_prices.columns.difference(sr_sc_prices.index)
        if len(missing_stock_price) > 0:
            if len(missing_stock_price) < 10:
                lggr.warning(f"Some stock prices are missing from {SIAMCHART_PRICE_URL}: {missing_stock_price}")
            else:
                lggr.warning(f"Some stock prices are missing from {SIAMCHART_PRICE_URL}. "
                             f"Stock names are recorded in {__SIAMCHART_MISSING_FILE}.")
                with open(__SIAMCHART_MISSING_FILE, 'w') as f:
                    f.writelines('\n'.join(missing_stock_price))
                lggr.warning(f"Missing names = {len(missing_stock_price)}/{len(df_prices.columns)}. "
                             f"Nevertheless, this is the expected behaviour from this external source.")
        sr_latest_prices = sr_sc_prices
        # noinspection PyUnresolvedReferences
        sc_sourced_stocks = sr_sc_prices.index[sr_sc_prices.index.isin(df_prices.columns)]
        df_prices.loc[pd.Timestamp(sc_date), sc_sourced_stocks] = sr_latest_prices
        df_price_source.loc[pd.Timestamp(sc_date), sc_sourced_stocks] = "siamchart"
    # Checking to see if the prices on latest date is "abundant". Sometimes yfinance is a little retarded.
    # Updated: the latest date price should be fine since we got the data from alternative module.
    latest_date_ts: pd.Timestamp = df_prices.index.max()
    na_cutoff: float = 0.40
    if df_prices.loc[latest_date_ts].isna().sum() >= na_cutoff * n_stock:  # If na more than 10% of stocks
        lggr.info(f"Data shows the latest date is {latest_date_ts.date()}."
                  f"However, there are more than {na_cutoff * 100:.1f}% of the stock price missing. "
                  f"Therefore, the price on this day is dropped entirely.")
        df_prices = df_prices.drop(labels=latest_date_ts, axis=0)
        latest_date_ts = df_prices.index.max()  # re-derive: the row we were pointing at is gone
    lggr.info(f"Price data are available "
              f"from {df_prices.index.min().strftime('%Y-%m-%d')} "
              f"to {df_prices.index.max().strftime('%Y-%m-%d')}.")

    # Realign volume to whatever df_prices ended up being (siamchart append / na-cutoff drop above
    # can add/remove rows after df_volume was first built) - missing volume just means patterns don't confirm.
    df_volume = df_volume.reindex(index=df_prices.index, columns=df_prices.columns)

    # Stats: Fundamentals
    df_stats_fundamentals: pd.DataFrame
    if not SKIP_STOCK_STATISTICS:
        lggr.info("Download all required stock statistics")
        df_stats = get_stock_statistics(stock_list, threads=N_THREADS, logger=lggr)
        df_stats.index = map(lambda _s: f"{_s}.BK" if '.BK' not in _s else _s, df_stats.index)

        # reindex (not a plain column select) so a field yfinance doesn't return for a given
        # stock becomes NaN instead of raising and dropping the friendly column renaming for everyone.
        df_stats_fundamentals = df_stats.reindex(columns=list(REQUIRED_STATS_FUNDAMENTALS.keys())).copy()
        df_stats_fundamentals.columns = list(REQUIRED_STATS_FUNDAMENTALS.values())

        # Backfill fields Yahoo didn't return this run (e.g. rate-limited) from the last successful
        # run's cache. Fundamentals change quarterly, so a stale value is far better than NaN.
        if os.path.isfile(__LATEST_STOCK_STATS_FULLPATH):
            df_stats_fundamentals_cached = pd.read_csv(__LATEST_STOCK_STATS_FULLPATH, index_col=0)
            df_stats_fundamentals = df_stats_fundamentals.combine_first(df_stats_fundamentals_cached) \
                .reindex(df_stats_fundamentals.index)

        # df_stats_fundamentals can contain stocks yfinance had fundamentals for but that got
        # dropped from df_prices (insufficient price history) - only compute 52wHighToClosePrice
        # for stocks present in both.
        for s in df_stats_fundamentals.index.intersection(df_prices.columns):
            last_close_price = df_prices.loc[latest_date_ts, s]
            high_to_close = df_stats_fundamentals.loc[s, '52wHigh'] / last_close_price - 1.0
            df_stats_fundamentals.loc[s, '52wHighToClosePrice'] = high_to_close
    else:
        df_stats_fundamentals = pd.DataFrame()  # Empty df. Needs for later part of the code.

    # Calculation Starts
    df_returns = pd.DataFrame(index=df_prices.index,
                              columns=pd.MultiIndex.from_product([df_prices.columns, PERIODS],
                                                                 names=['SecCode', 'Period']),
                              dtype=float)

    for p in PERIODS:
        df_p_shifted = df_prices.shift(p)
        df_returns_p: pd.DataFrame = (df_prices - df_p_shifted) / df_p_shifted
        df_returns.loc[:, (slice(None), p)] = df_returns_p.values

    # Keeps only date that is greater than the ordered start date
    df_returns = df_returns.loc[(df_returns.index >= return_start_date)]

    if DAILY_OPERATION:
        filling_mode = DAILY_FILLING_MODE  # overriding everything with default value
    else:
        filling_mode = FORWARD_FILL
    lggr.debug(f"Filling mode = {filling_mode}{', overridden by DAILY_OPERATION = True' if DAILY_OPERATION else ''}")
    if filling_mode != 'none':
        """
        # As of 9 May 2022, [PEACE.BK, TKC.BK] is a good newly listed stock to visualize this.
        df_returns.stack(level=0, dropna=False).loc[(slice(None), ['PEACE.BK', 'TKC.BK']), :]
        df_returns.stack(level=0, dropna=False).loc[(slice(None), ['PEACE.BK', 'TKC.BK']), :].ffill(axis=1)
        (df_returns.stack(level=0, dropna=False).loc[(slice(None), ['PEACE.BK', 'TKC.BK']), :]
        .ffill(axis=1).unstack().swaplevel(axis=1))
        """
        if filling_mode == 'longest':
            lggr.info("Filling na returns with longest available return for each date.")
            for s in df_prices.columns:
                sr_prices_s = df_prices[s]
                first_avail_date = sr_prices_s.notna().idxmax()
                first_price = sr_prices_s[first_avail_date]
                if DAILY_OPERATION:
                    df_return_s = df_returns.iloc[[-1]][s]
                else:
                    df_return_s = df_returns[s]  # Entire slice
                for d, sr_returns_d in df_return_s.iterrows():
                    if sr_returns_d.isna().any():  # There is a nan return.
                        first_na_period = sr_returns_d.isna().idxmax()
                        ret_s_d = sr_prices_s[d] / first_price - 1
                        lggr.debug(f"Replace ROC[{first_na_period}] of {s} with {ret_s_d:.4f} "
                                   f"(b/w {first_avail_date.strftime('%Y-%m-%d')} to {d.strftime('%Y-%m-%d')})")
                        df_returns.loc[d, (s, first_na_period)] = ret_s_d
        lggr.info("Forward-filling across (increasing) period for stock with na returns.")
        df_returns = df_returns.stack(level=0, dropna=False).ffill(axis=1).unstack().swaplevel(axis=1)

    # df_returns.T.groupby(level=1).groups  # Confirmation
    # pandas 2.x: groupby(axis=1) removed → transpose workaround
    df_period_ranks: pd.DataFrame = df_returns.T.groupby(level=1).rank(pct=True).T.swaplevel(axis=1)

    # RS Rating
    # pandas 2.x: groupby(axis=1) removed → stack + weighted sum
    _weights_s = pd.Series(WEIGHTS, index=PERIODS)
    df_rs = (df_returns
             .stack(level=0, dropna=False)
             .mul(_weights_s, axis=1)
             .sum(axis=1, min_count=1)
             .unstack(level=1))
    df_rs_rank = df_rs.rank(axis=1, pct=True)

    if len(df_rs_rank.index.difference(df_period_ranks.index)):
        pass  # place for warning

    # %% Stats: Technical (price/volume only - replaces fundamentals as the extra-info columns)
    lggr.info("Computing technical pattern signals (base tightness, breakout, market/sector regime).")
    # latest_date_ts already computed earlier (post price-finalization, incl. re-derivation after the
    # na_cutoff drop) - not recomputed here since nothing between there and here touches df_prices' index.

    df_high_n = df_prices.rolling(BASE_LOOKBACK).max()
    df_low_n = df_prices.rolling(BASE_LOOKBACK).min()
    df_tight_base = ((df_high_n - df_low_n) / df_low_n) <= BASE_TIGHTNESS_MAX

    df_prior_high = df_prices.shift(1).rolling(BREAKOUT_LOOKBACK).max()
    df_vol_ratio = df_volume / df_volume.rolling(VOLUME_AVG_WINDOW).mean().replace(0, np.nan)
    df_breakout = (df_prices > df_prior_high) & (df_vol_ratio >= BREAKOUT_VOLUME_MULT)

    sr_high_to_close_252d = df_prices.rolling(252).max().loc[latest_date_ts] / df_prices.loc[latest_date_ts] - 1.0

    # Market regime: equal-weight proxy built from the already-downloaded SET universe itself,
    # rather than guessing an external index ticker symbol.
    sr_market_index = (1 + df_prices.pct_change(fill_method=None).mean(axis=1).fillna(0)).cumprod()
    sr_market_regime_up = sr_market_index > sr_market_index.rolling(MARKET_TREND_WINDOW).mean()

    # Liquidity proxy (replaces marketCap as the "can I actually size into this" filter).
    sr_liquidity_20d = (df_prices * df_volume).rolling(20).mean().loc[latest_date_ts]

    # Sector RS: reuse the Sector column already scraped in the SET listed-company table -
    # no separate sector-index download needed. SET marks funds/REITs/unclassified names with
    # Sector == '-' ; averaging RS across that bucket would fabricate a meaningful-looking number
    # for names that aren't really comparable, so it's excluded from the sector grouping (NaN'd instead).
    sr_stock_sector = get_SET_stock_sectors().reindex([s.split('.')[0] for s in df_rs_rank.columns])
    sr_stock_sector.index = df_rs_rank.columns
    sr_stock_sector_classified = sr_stock_sector.replace(['-', 'nan'], np.nan)
    df_sector_rs = df_rs_rank.T.groupby(sr_stock_sector_classified).mean().T  # date x sector, avg RS Score per sector

    df_stats_technical = pd.DataFrame(index=df_prices.columns)
    df_stats_technical['TightBase'] = df_tight_base.loc[latest_date_ts]
    df_stats_technical['BreakoutVolumeConfirmed'] = df_breakout.loc[latest_date_ts]
    df_stats_technical['VolumeRatio'] = df_vol_ratio.loc[latest_date_ts]
    df_stats_technical['HighToClose_252d'] = sr_high_to_close_252d
    df_stats_technical['AvgValue_20d'] = sr_liquidity_20d
    df_stats_technical['MarketRegimeUp'] = sr_market_regime_up.loc[latest_date_ts]
    df_stats_technical['Sector'] = sr_stock_sector
    df_stats_technical['SectorRS'] = sr_stock_sector_classified.map(df_sector_rs.loc[latest_date_ts])

    if not sr_market_regime_up.loc[latest_date_ts]:
        lggr.warning(f"Market regime (equal-weight SET proxy) is currently in a DOWNTREND "
                    f"(below its {MARKET_TREND_WINDOW}-day average) - "
                    f"consider reducing new long exposure regardless of RS Score.")

    # At this point, we collect df_rs_rank, df_rs, df_period_ranks,
    if DAILY_OPERATION:
        date_to_produce: list[datetime.date] = [df_prices.index.max().date()]
    else:
        date_to_produce: list[datetime.date] = (df_returns
                                                .index
                                                .astype('datetime64[ns]')
                                                .values
                                                .astype('datetime64[D]')
                                                .tolist())  # Everyday
    list_output_years = sorted(list(set([d.year for d in date_to_produce])))

    excel_opening_attempts: int = 0
    excel_max_attempt: int = 3
    excel_success: bool = False
    dict_writers: dict = dict()
    while not excel_success and excel_opening_attempts < excel_max_attempt:
        try:
            if DAILY_OPERATION:
                singular_y = date_to_produce[0].year
                today_str = datetime.date.today().strftime("%Y%m%d")
                dict_writers = {singular_y: (pd.ExcelWriter(f'./backup/{today_str}_'
                                                            f'{dt_script_start_str}.xlsx'),
                                             pd.ExcelWriter(f'./{today_str}.xlsx'))}
            else:
                dict_writers = {y: (pd.ExcelWriter(f'./backup/{y}_{dt_script_start_str}.xlsx'),
                                    pd.ExcelWriter(f'./{y}.xlsx')) for y in list_output_years}
            excel_success = True
        except PermissionError as e:
            if excel_opening_attempts < excel_max_attempt:
                excel_opening_attempts += 1
                lggr.critical(f"(Attempt = {excel_opening_attempts}) "
                              "Some required excel files are being used. "
                              "Retrying in 10 seconds... (close the Excel file to proceed)")
                import time; time.sleep(10)
    if not excel_success:
        raise RuntimeError("Cannot write excel!!!")

    for d in date_to_produce:
        # noinspection PyTypeChecker
        ts_d = pd.Timestamp(d)

        y = d.year
        writer_backup, writer_recent = dict_writers[y]

        sr_rs_rank_d = df_rs_rank.loc[ts_d]
        df_period_ranks_d: pd.DataFrame = df_period_ranks.loc[ts_d]
        sr_rs_d = df_rs.loc[ts_d]
        df_roc_d = df_returns.loc[ts_d].unstack().rename(lambda _s: f"ROC[{_s}]", axis=1)
        sr_source_d = df_price_source.loc[ts_d]
        sr_prices_d = df_prices.loc[ts_d]

        """
        # Requirement changes: remove ROC. Only keeping the ROC Ranking itself.
        df_output_d: pd.DataFrame = (df_roc_d.join(df_period_ranks_d
                                                   .unstack(level=0)
                                                   .rename(lambda _s: f"ROC Score[{_s}]", axis=1)))
        """
        df_output_d: pd.DataFrame = df_period_ranks_d.unstack(level=0).rename(lambda _s: f"ROC Score[{_s}]", axis=1)
        df_output_d[f'RS Rating (Type {filling_mode})'] = sr_rs_d
        df_output_d[f'RS Score'] = sr_rs_rank_d
        df_output_d['Close Price'] = sr_prices_d
        df_output_d['Price Source'] = sr_source_d

        df_output_d.sort_values(by=f'RS Rating (Type {filling_mode})', ascending=False, inplace=True)
        if ts_d == latest_date_ts:
            df_output_d = df_output_d.join(df_stats_fundamentals).join(df_stats_technical)
        for writer in [writer_backup, writer_recent]:
            df_output_d.to_excel(writer, sheet_name=d.strftime("%Y%m%d"))
    for writer_backup, writer_recent in dict_writers.values():
        lggr.info(f"Writing backup output file to {writer_backup.__fspath__()}")
        writer_backup.close()
        lggr.info(f"Writing main output file to {writer_recent.__fspath__()}")
        writer_recent.close()

    if PRODUCE_WATCHLIST:
        watchlist_filename = f'watchlist_{dt_script_start_str}.txt'
        watchlist_stock = df_rs_rank
        sr_rs_rank_d = df_rs_rank.loc[df_prices.index.max()].sort_values(ascending=False)
        rs_rank_top_yf = sr_rs_rank_d.index[sr_rs_rank_d >= RANKING_THRESHOLD]
        lggr.info(f"Stocks with (RS Score >= {RANKING_THRESHOLD * 100:.1f}) = "
                  f"{len(rs_rank_top_yf)}/{len(sr_rs_rank_d)}")
        rs_rank_top_trading_view = [f"SET:{s.split('.')[0]}" for s in rs_rank_top_yf]
        with open(watchlist_filename, 'w') as watch_f:
            watch_f.writelines('\n'.join(rs_rank_top_trading_view))
    if not SKIP_DATA_DUMP:
        lggr.info("Dumping backup outputs")
        lggr.info(f"Dumping close prices to {__LATEST_DOWNLOADED_PRICE_FULLPATH}")
        df_prices.to_csv(__LATEST_DOWNLOADED_PRICE_FULLPATH)
        lggr.info(f"Dumping volumes to {__LATEST_DOWNLOADED_VOLUME_FULLPATH}")
        df_volume.to_csv(__LATEST_DOWNLOADED_VOLUME_FULLPATH)
        lggr.info(f"Dumping returns to {__LATEST_COMPUTED_RETURN_FULLPATH}")
        df_returns.to_csv(__LATEST_COMPUTED_RETURN_FULLPATH)
        if not SKIP_STOCK_STATISTICS and not df_stats_fundamentals.empty:
            lggr.info(f"Dumping stock statistics to {__LATEST_STOCK_STATS_FULLPATH}")
            df_stats_fundamentals.to_csv(__LATEST_STOCK_STATS_FULLPATH)
    else:
        lggr.info("Writing return and price routine skipped.")
    print("Script executed successfully.")
