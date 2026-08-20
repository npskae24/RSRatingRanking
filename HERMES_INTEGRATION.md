# Integrating RS Rating Ranking with Hermes Agent

How to wire this project's `stock_ranking.py` pipeline into
`hermes-agent` (`C:\Users\PongsakornNivesvivat\AppData\Local\hermes\hermes-agent`).
Findings below come from reading `hermes-agent`'s `AGENTS.md`, `cron/jobs.py`,
and `hermes_cli/subcommands/cron.py` directly — not guessed.

## Hermes' design principle: Footprint Ladder

Hermes deliberately avoids adding new agent-facing tools when a lower rung
already does the job (every new tool gets sent on every API call, so it's
expensive). The rungs, low to high:

1. Extend existing code
2. **CLI command + skill** — "Default choice for subscriptions, scheduled
   tasks, service setup."
3. Service-gated tool
4. Plugin (`~/.hermes/plugins/`)
5. MCP server in the catalog
6. New core tool (last resort)

For this project, rung 2 (cron + skill) is enough — no MCP server or new
Hermes tool needed.

## Option 1: Cron job (recommended — no agent-facing code needed)

Hermes cron jobs support a `script` field: a script that runs on schedule,
whose stdout either feeds the agent's prompt as context, or (with
`--no-agent`) *is* the whole job, delivered verbatim.

**Constraint that matters**: script paths resolve under `~/.hermes/scripts/`
only — you can't point `--script` directly at an arbitrary path like
`D:\Stocktrading\RSRatingRanking-master\stock_ranking.py`. `.sh`/`.bash`
files run via bash, everything else via Python. So the pattern is: drop a
thin wrapper under `~/.hermes/scripts/` that `cd`s into this repo and runs
the real pipeline.

Example wrapper `~/.hermes/scripts/rs_rating_run.py`:
```python
import subprocess, sys, glob, os

REPO = r"D:\Stocktrading\RSRatingRanking-master"
subprocess.run([sys.executable, "stock_ranking.py"], cwd=REPO, check=True)

# print the freshest watchlist so cron can inject/deliver it
files = sorted(glob.glob(os.path.join(REPO, "watchlist_*.txt")), key=os.path.getmtime)
if files:
    print(open(files[-1]).read())
```

Create the job (flag-based CLI, no conversational agent round-trip needed):
```
hermes cron create "0 17 * * 1-5" --script rs_rating_run.py --workdir "D:\Stocktrading\RSRatingRanking-master" --name "rs-rating-daily" --deliver origin
```
- `"0 17 * * 1-5"` — Mon–Fri 17:00 local, after SET closes (16:30). Hermes
  also accepts `"every 2h"` / `"30m"` style shorthand if a fixed clock time
  isn't wanted.
- `--workdir` sets the cwd for terminal/file tools during the run and
  injects this repo's `CLAUDE.md` as context — separate from where
  `--script` itself resolves from (`~/.hermes/scripts/`).
- Add `--no-agent` if you just want the watchlist delivered as-is, with
  zero LLM reasoning — cheapest option, classic watchdog pattern. Omit it
  (as above) if you want the agent to read the watchlist and, say, summarize
  top movers or cross-check against a portfolio before delivering.

To edit or inspect later: `hermes cron edit <job_id> ...`, `hermes cron list`,
`hermes cron runs <job_id>`.

## Option 2: Skill (for on-demand, in-chat use)

If you also want to ask Hermes for a rating check mid-conversation (not just
on a schedule), add a `SKILL.md` under `skills/<category>/rs-rating-th/`
telling the agent: "run `python stock_ranking.py` in
`D:\Stocktrading\RSRatingRanking-master`, then read the latest `{date}.xlsx`
/ `watchlist_*.txt` with the terminal and file tools you already have."
This needs no new Hermes tool — the agent's existing terminal/file tools are
enough, which is exactly what the Footprint Ladder prefers over building a
dedicated tool.

## Option 3: MCP server (only if you need structured queries)

Only worth it if something needs to ask "what's PTT's RS rating right now?"
programmatically rather than through cron/chat. Given the ladder's guidance
and that options 1–2 cover the actual use case, skip this unless a concrete
need shows up.

## Known gaps before relying on this in production

Carried over from `CLAUDE.md` in this repo — matters for a cron job too:

- `SKIP_STOCK_STATISTICS = False` now — fundamentals fetch via
  `yfinance.Ticker(...).info` instead of the discontinued `quoteSummary` v11
  API, verified working from this dev machine. Not yet verified from a VPS —
  Yahoo's unofficial endpoint may rate-limit a datacenter IP harder than a
  residential one; watch the first few cron runs for `ConnectionError` spam
  in the log before trusting this unattended.
- `SKIP_TODAY_PRICE_DOWNLOAD = True` currently — the Selenium/siamchart
  fallback needs a chromedriver version matching whatever Chrome is
  installed on the machine actually running the cron job; none of the
  versions under `driver/` matched Chrome 151 in this dev environment.
- If the cron job runs unattended for weeks, SET's Incapsula WAF has been
  observed to rate-limit an IP after repeated requests in a short window —
  a transient empty-page failure on `download_SET_stock_names_html()` is
  more likely that than a real regression.
- `set_stock_list/th_holidays.csv` is manually maintained and goes stale
  silently (warning only, no failure) — worth a periodic manual check if
  this becomes a long-running daily cron job.
