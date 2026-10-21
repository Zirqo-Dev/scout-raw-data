# scout-raw-data

A raw, hourly log of GeckoTerminal pool data for the Base network. Raw only:
no scores, tiers, filters, holders, dashboard or hypotheses. Each pool's
GeckoTerminal attributes are stored verbatim, with the included token objects
verbatim beside them.

## Universe

Fixed in `UNIVERSE` in `scripts/log_base.py` and recorded in every meta file.
All calls go to `https://api.geckoterminal.com/api/v2` with
`include=base_token,quote_token,dex`, no API key, 2.5 s apart, retrying 429
and 5xx with backoff.

| source       | endpoint                                                     | pages |
|--------------|--------------------------------------------------------------|-------|
| `trending`   | `/networks/base/trending_pools?page=N`                       | 1-5   |
| `top_volume` | `/networks/base/pools?page=N&sort=h24_volume_usd_desc`       | 1-5   |
| `new`        | `/networks/base/new_pools?page=N`                            | 1-2   |

Pools are deduped by address across sources. A pool's row lists every source
it appeared in and its rank in each (rank = (page - 1) * 20 + position).
Changes to the universe are logged in `docs/CHANGES.md`.

## Files

```
data/base/YYYY-MM-DD/HHMMSS.jsonl.gz   one row per pool, one file per run, never rewritten
data/base/YYYY-MM-DD/HHMMSS.meta.json  ts, script_version, universe, calls, ok, errors, pools_written, duration_s
data/base/latest.json                  overwritten each run: a small subset of fields per pool
```

Row shape:

```
{"ts", "network": "base", "pool", "sources", "ranks",
 "attributes", "relationships": {"base_token", "quote_token", "dex"},
 "base_token_attr", "quote_token_attr"}
```

`ts` is the run's start time (UTC). `script_version` is the `git hash-object`
of `scripts/log_base.py`. A run where every call fails still writes its meta
file and goes red; the gz file and `latest.json` are not written.

## Cadence

`log.yml` runs hourly, started by cron-job.org via `workflow_dispatch`.
`watchdog.yml` runs on GitHub's own schedule at :41 and opens the issue
"scout-raw alert: base log stale" when the newest meta file with
`pools_written > 0` is more than three hours old, closing it when the log is
fresh again. All-fail runs commit their meta file but do not reset that clock,
so a GeckoTerminal outage alerts after three hours too.

## Why a separate repo

This repo is separate from
[hoodscout-data](https://github.com/Zirqo-Dev/hoodscout-data) on purpose. It
holds raw exploratory data only, and nothing here is evidence for any
hypothesis registered there. A future HoodScout dashboard tab may read
`data/base/latest.json`.

## Tests

```
pip install -r requirements-test.txt
python -m pytest -q
```

Fixtures only, no network. Fixture addresses are synthetic.
