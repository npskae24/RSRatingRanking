# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A script that computes IBD-style **RS Rating** (Relative Strength percentile rank) for every stock listed on the Thai SET exchange, ranks them, writes Excel output, and produces a TradingView-format watchlist of top-ranked stocks. A Flask dashboard wraps the script for interactive use.

## Commands

No `requirements.txt`/`pyproject.toml` exists. **`python` on PATH may resolve to an unrelated venv missing deps (e.g. `selenium`) — use `py -3.12` (Windows py launcher) explicitly, not bare `python`, to hit the interpreter with everything installed.** The checked-in `venv/` is **broken** — it was created on a different machine (`C:\Users\Bank\...`) and its `pyvenv.cfg` points at a Python interpreter path that doesn't exist here. Don't try to activate it; use the system Python instead (this repo has been run successfully under Python 3.12, which already has pandas/numpy/yfinance/selenium/flask/requests/psutil installed — `html5lib` is the one package that had to be added manually, see below).

Run the ranking script directly (CLI, writes files to the repo root):
```
py -3.12 stock_ranking.py
```

Run the web dashboard (wraps `stock_ranking.py` as a subprocess via `sys.executable`, streams logs via SSE at http://localhost:5000):
```
py -3.12 app.py
```

There is no test suite and no lint config in this repo.

`stock_ranking_cli.py` is an unfinished argparse stub — not wired to anything, don't treat it as the entry point.

## Architecture

**`stock_ranking.py`** is the entire pipeline, run top-to-bottom under `if __name__ == '__main__':` (not organized into callable functions except a few I/O helpers). Reading the config constants block near the top (`PERIODS`, `WEIGHTS`, `RANKING_THRESHOLD`, `DAILY_OPERATION`, etc.) first is the fastest way to understand behavior — most tuning happens by editing these module-level constants, not the pipeline logic.

Pipeline flow:
1. **Stock universe** — scrape SET's listed-companies page (`download_SET_stock_names_html`) into `set_stock_list/`, parse the HTML table for symbols, then drop anything in `exclusion_list.txt`. `exclusion_list.txt` naturally accumulates dead entries for stocks that get delisted later — a non-matching entry is silently a no-op (`except ValueError: pass`), which is normal, not a bug to fix.
2. **Price history** — bulk-download close prices via `yfinance.download()` for all `{symbol}.BK` tickers. **`start=` must be a Python `datetime.date`, not `numpy.datetime64`** — `np.busday_offset(...)` returns `numpy.datetime64`, and newer `yfinance` raises `ValueError` for every ticker if you pass that directly (see Known issues below); the call site does `.astype(datetime.date)` right before the `yfinance.download()` call for this reason — don't remove it, and don't apply `.astype()` further upstream since `return_start_date`/`start_download_date` are also compared against a `DatetimeIndex` elsewhere and need to stay `numpy.datetime64`/`pd.Timestamp`-comparable there. If today's date isn't present in the yfinance result (common when the market hasn't closed yet), it falls back to scraping `siamchart.com` with Selenium (`download_siamchart_prices`) — this path is currently unusable in this dev environment (see Known issues) and is normally avoided by setting `SKIP_TODAY_PRICE_DOWNLOAD = True`.
3. **Fundamentals** — `yahoo_finance_scraper.get_stock_statistics()` fetches per-symbol via `yfinance.Ticker(...).info` (multiprocessed, `N_THREADS` workers, jittered + retried to avoid bursting Yahoo's unofficial endpoint), for ROE, margins, market cap, 52w high, quarterly revenue/earnings growth. This step is enabled (`SKIP_STOCK_STATISTICS = False`); the RS Rating itself doesn't depend on it, only the extra output columns (`ROE`, `marketCap`, `52wHighToClosePrice`, etc.) do. `REQUIRED_STATS_FUNDAMENTALS` in `stock_ranking.py` maps yfinance's flat `.info` field names to friendly output column names — selection uses `.reindex()` (not a plain column select) so a field yfinance doesn't return for one stock becomes `NaN` instead of an exception that silently drops the friendly renaming for every stock. `df_stats_fundamentals`'s index isn't guaranteed to be a subset of `df_prices.columns` (a stock can have fundamentals but get dropped from price data for insufficient history) — the `52wHighToClosePrice` loop must iterate `.index.intersection(df_prices.columns)`, not the raw index, or it raises `KeyError`.
4. **RS calculation** — returns computed over four lookback windows (`PERIODS = [63,126,189,252]` trading days ≈ 3/6/9/12 months), each percentile-ranked, then combined into one RS score via `WEIGHTS = [0.4,0.2,0.2,0.2]` (heaviest weight on the shortest/most recent period) and percentile-ranked again into the final RS Rating.
5. **Output** — writes two Excel copies per run (`backup/{date}_{timestamp}.xlsx` for history, `{date}.xlsx` at repo root as "latest"), plus `watchlist_{timestamp}.txt` (TradingView `SET:XXX` format) for stocks at/above `RANKING_THRESHOLD` (default 0.8 = top 20%). Also dumps `backup/close_price.csv` and `backup/return.csv` so a future run can skip re-downloading (`SKIP_PRICE_DOWNLOAD`).

Note: several spots (`df_returns.T.groupby(level=1)...`, the RS weighted-sum block) use transpose/stack workarounds specifically because pandas 2.x removed `groupby(axis=1)` — don't "simplify" these back to the old `axis=1` form.

**`app.py`** is a thin Flask wrapper: `/api/run` spawns `stock_ranking.py` as a subprocess and streams its stdout to the browser over SSE (`/api/stream`); `/api/results` reads the latest `{date}.xlsx` and returns the top 200 rows as JSON; `/api/watchlist` and `/api/files` expose the other generated artifacts. It never imports pipeline logic directly — it only shells out to the script and reads the files it produces.

**`yahoo_finance_scraper.py`** is a standalone utility module (no dependency on `stock_ranking.py`) for pulling arbitrary Yahoo Finance `quoteSummary` modules for a list of symbols in parallel via `multiprocessing`. See Known issues — the endpoint it hits no longer exists.

## Config knobs (top of `stock_ranking.py`)

- `DAILY_OPERATION` — `True` computes only today's rating (normal use); `False` recomputes RS ratings for the full history back to `GLOBAL_START_DATE` (slow, used for backfills/one-off repopulation).
- `SKIP_*` flags — skip network calls (name download, price download, stats download) and reuse local cache from `backup/`, useful for iterating on ranking logic without re-hitting Yahoo/SET. `SKIP_TODAY_PRICE_DOWNLOAD` is still `True` (chromedriver mismatch below is unfixed). `SKIP_STOCK_STATISTICS` is now `False` — fundamentals are fetched via `yfinance.Ticker.info` (see Architecture above), which adds real per-run network time (~800 stocks / `N_THREADS` workers, throttled) that didn't exist while this was skipped.
- `DAILY_FILLING_MODE` / `FORWARD_FILL` — how missing returns are handled for recently-listed stocks with insufficient price history.

## Known issues / fragile external integrations

These were hit and diagnosed by running the pipeline end-to-end; each is either fixed in code or worked around with a config flag — read this before "fixing" something that's already accounted for.

- **SET's stock-list endpoint requires a browser-like `User-Agent`.** `download_SET_stock_names_html()` now sends `headers=HEADERS` (imported from `yahoo_finance_scraper`) — without it, SET's Incapsula WAF returns HTTP 200 with an empty bot-challenge page instead of the real HTML table, and `pd.read_html()` fails confusingly (`No tables found` or a `html5lib` import error, depending on flavor fallback). Incapsula can also rate-limit an IP for a while after repeated requests in a short window (seen firsthand while debugging) — a sudden reappearance of the empty-page symptom after this was already fixed is more likely transient rate-limiting than a regression.
- **`pd.read_html()` needs `html5lib` installed**, not just `lxml`. SET's HTML is malformed enough that the strict `lxml` parser raises `No tables found` on it; pandas' default flavor order falls through to `bs4`, which hard-requires `html5lib`. Install with `pip install html5lib` if missing.
- **Yahoo's `quoteSummary` v11 API (`query2.finance.yahoo.com/v11/finance/quoteSummary/...`) has been discontinued** — every request now returns HTTP 404. `yahoo_finance_scraper.py` no longer uses it — it fetches via `yfinance.Ticker(...).info` instead, which handles Yahoo's `v10` crumb+cookie auth internally and has been verified working for `.BK` tickers (confirmed live: `marketCap`, `returnOnEquity`, `profitMargins`, `fiftyTwoWeekHigh`, `revenueGrowth`, `earningsQuarterlyGrowth`, `totalRevenue`, `netIncomeToCommon` all present). It's an unofficial API surface, so Yahoo may still rate-limit a datacenter IP (e.g. a VPS) harder than this dev machine — if `get_single_stock_statistics` starts raising `ConnectionError` for most/all stocks, that's the first thing to suspect, not a logic bug.
- **`driver/chromedriver_v131.exe` doesn't match the Chrome actually installed in this dev environment** (Chrome 151 at last check), and no matching version exists under `driver/`. The Selenium/siamchart fallback path (triggered when yfinance lacks today's price) will fail with `FileNotFoundError` if exercised. Worked around via `SKIP_TODAY_PRICE_DOWNLOAD = True`; a real fix means downloading a matching chromedriver.
- **`th_holidays.csv`** (`set_stock_list/th_holidays.csv`) is a manually-maintained list that goes stale — the script only warns when it's behind today's date, it doesn't fail. Long stretches of stale holidays can silently skew the daily download-window calculation around holiday dates.

## Data directories

- `backup/` — timestamped Excel snapshots + `close_price.csv`/`return.csv` cache, growing unbounded (no cleanup logic exists).
- `log/` — one timestamped log file per run.
- `set_stock_list/` — timestamped snapshots of the scraped SET company list HTML + `th_holidays.csv` (manually maintained; the script warns if it's stale).
