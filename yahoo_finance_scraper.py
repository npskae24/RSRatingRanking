import logging
import random
import time
from itertools import repeat
from typing import Union

import multiprocessing as mp
import pandas as pd
import psutil
import yfinance


# Const: Connection
MAX_RETRIES: int = 3
TIMEOUT: list[float] = [2.0, 5.0, 10.0]  # backoff delay (seconds) before each retry, length must = MAX_RETRIES
__PROXIES = None
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                         '(KHTML, like Gecko) Chrome/102.0.5005.61 Safari/537.36'}


def __get_null_logger():
    logger = logging.getLogger()
    logger.addHandler(logging.NullHandler())
    return logger


def get_single_stock_statistics(stock: str,
                                logger: logging.Logger = None,
                                return_dict: bool = False) -> Union[pd.Series, dict]:
    """Fetch fundamentals for one stock.

    Yahoo's quoteSummary v11 API (used here previously) was discontinued and now 404s
    on every request. yfinance's Ticker.info still works for .BK tickers - it handles
    the v10 crumb/cookie auth internally - so we use that instead of hitting Yahoo directly.
    """
    if logger is None:
        logger = __get_null_logger()
    if '.BK' not in stock:
        stock = f"{stock}.BK"
    logger.info(f"Process ID {psutil.Process().pid} downloading fundamentals for {stock} via yfinance.")

    info = None
    for i in range(MAX_RETRIES):
        time.sleep(random.uniform(0.5, 1.5))  # throttle: avoid bursting Yahoo's unofficial endpoint
        try:
            info = yfinance.Ticker(stock).info
            if info and info.get('marketCap') is not None:
                break
            logger.debug(f"Attempt {i + 1} for {stock} returned no usable data.")
        except Exception as e:
            logger.debug(f"Attempt {i + 1} for {stock} failed: {e}")
        time.sleep(TIMEOUT[i])

    if not info:
        raise ConnectionError(f"Fail to process the stock {stock}.")

    sr_stats = pd.Series(info, name=stock)
    if return_dict:
        return info
    return sr_stats


def _multiple_pull_wrapper(s: str, lggr: logging.Logger = None):
    try:
        return get_single_stock_statistics(s, logger=lggr)
    except Exception as e:
        error_str = f"Encountered an error while processing stock {s}: \n\t{e}"
        if lggr is None:
            print(error_str)
        else:
            lggr.critical(error_str)


def get_stock_statistics(stocks: Union[list[str], str],
                         threads: Union[int, bool] = False,
                         logger: logging.Logger = None) -> pd.DataFrame:
    _s = [stocks] if isinstance(stocks, str) else stocks

    if not isinstance(threads, bool):
        use_mp = True
        n_t = threads
    elif threads:
        use_mp = True
        n_t = psutil.cpu_count(logical=True)
    else:
        use_mp = False
        n_t = 0

    if use_mp:
        with mp.Pool(processes=n_t) as p:
            outputs = p.starmap(_multiple_pull_wrapper, zip(_s, repeat(logger)))
    else:
        outputs = list()
        for s in stocks:
            outputs.append(_multiple_pull_wrapper(s, logger))

    s_out = [s for s, o in zip(stocks, outputs) if o is not None]
    o_out = [o for s, o in zip(stocks, outputs) if o is not None]
    df = pd.DataFrame(o_out, index=s_out).sort_index()
    return df
