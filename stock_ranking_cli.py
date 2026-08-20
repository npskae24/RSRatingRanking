import sys
import argparse


"""
# Const: Configurable
GLOBAL_START_DATE: datetime.date = datetime.date(2020, 1, 1)
FORWARD_FILL: Literal['shortest', 'ffill', 'none'] = 'none'

RANKING_THRESHOLD:    float = 0.8
SKIP_NAME_DOWNLOAD:    bool = False  # Skip downloading stock names from SET exchange
SKIP_PRICE_DOWNLOAD:   bool = False  # Skip downloading price from Yahoo Finance
SKIP_STOCK_STATISTICS: bool = False   # Skip downloading statistics of the stocks using custom module
SKIP_DATA_DUMP:        bool = False  # Skip downloaded price, calculated returns dump at the end of script
PRODUCE_WATCHLIST:     bool = True   # Producting watchlist_{date}.txt

DAILY_OPERATION:       bool = True   # Script only computes the daily data.
DAILY_FILLING_MODE: Literal['shortest', 'ffill', 'none'] = 'shortest'

N_PRICE_THRESHOLD_DATE:       int = 5  # if no of stock price is less than this on a day, that day is discarded.
N_PRICE_THRESHOLD_UNDERLYING: int = 3  # If a stock has less that this no. price, then it is dropped.

PERIODS:   list[int] = [63, 126, 189, 252]  # in bars/trading days
WEIGHTS: list[float] = [0.4, 0.2, 0.2, 0.2]
"""


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", type=bool, help="Daily Operation Flag", )

    parser.parse_args(sys.argv)
