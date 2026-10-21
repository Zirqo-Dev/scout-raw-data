#!/usr/bin/env python3
"""Log raw GeckoTerminal pool snapshots for Base. Raw only.

One run fetches a fixed universe of pool-list pages, dedupes the pools by
address and writes them as they came: the pool's attributes verbatim, the ids
it points at, and the included token objects verbatim. Nothing is scored,
tiered, filtered or derived. Anything that wants a number computed from these
rows computes it downstream, from the files, where it can be redone.

Per run:
  data/base/YYYY-MM-DD/HHMMSS.jsonl.gz   one row per pool, never rewritten
  data/base/YYYY-MM-DD/HHMMSS.meta.json  what was asked, what came back
  data/base/latest.json                  a small copy for a dashboard tab,
                                         overwritten every run

Exits 1 when every call failed, after writing the meta file, so the run goes
red and the failure is still on disk. A partial failure exits 0: the meta
file's ok and errors say what was missed.
"""
import gzip
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

NETWORK = "base"
BASE = "https://api.geckoterminal.com/api/v2"
HEADERS = {"Accept": "application/json;version=20230302",
           "User-Agent": "scout-raw-data/0.1"}
INCLUDE = "base_token,quote_token,dex"
SPACING_S = 2.5          # between calls, as in hoodscout-data's collect.py
OUT_DIR = "data/base"

# The universe. Changing it changes what every later file means, so it moves
# only with Pete's approval and a dated line in docs/CHANGES.md.
#
# UNVERIFIED: sort=h24_volume_usd_desc on /pools. hoodscout-data never calls
# /pools, and neither the API nor its docs were reachable from the authoring
# environment. If the value is rejected, the meta file's errors will show a
# 4xx for those five calls on the first run.
UNIVERSE = (
    # (source, path, pages, extra query)
    ("trending",   f"/networks/{NETWORK}/trending_pools", 5, ""),
    ("top_volume", f"/networks/{NETWORK}/pools",          5, "&sort=h24_volume_usd_desc"),
    ("new",        f"/networks/{NETWORK}/new_pools",      2, ""),
)

# GeckoTerminal's page size. A rank is (page - 1) * PAGE_SIZE + position, so
# a failed page leaves a gap in the ranks rather than shifting every later
# pool up by twenty.
PAGE_SIZE = 20

LATEST_MAX_BYTES = 200 * 1024


def universe_calls():
    """-> [(source, page, path)] in the order they are fetched."""
    return [(source, page, f"{path}?page={page}{extra}&include={INCLUDE}")
            for source, path, pages, extra in UNIVERSE
            for page in range(1, pages + 1)]


def script_version(path=__file__):
    """git hash-object of this file, computed without git."""
    with open(path, "rb") as fh:
        body = fh.read()
    return hashlib.sha1(b"blob %d\0" % len(body) + body).hexdigest()


def get(path, tries=4):
    """collect.py's get(), retrying 5xx as well as 429. Backoff 20s, 40s,
    60s; the last failure is raised for the caller to count."""
    for i in range(tries):
        try:
            req = urllib.request.Request(BASE + path, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            retryable = e.code == 429 or 500 <= e.code < 600
            if not retryable or i == tries - 1:
                raise
            wait = 20 * (i + 1)
            print(f"  {e.code} on {path}, retrying in {wait}s")
            time.sleep(wait)


def error_key(e):
    """The status code for an HTTP error, else the exception's class name."""
    return str(e.code) if isinstance(e, urllib.error.HTTPError) else type(e).__name__


# ------------------------------------------------------------- parsing

def _rel_id(rel, key):
    return ((rel.get(key) or {}).get("data") or {}).get("id")


def _included(payload):
    """{(type, id): attributes} for the response's included[] objects."""
    out = {}
    for item in payload.get("included") or []:
        if isinstance(item, dict) and item.get("id"):
            out[(item.get("type"), item["id"])] = item.get("attributes")
    return out


def pool_address(item):
    """attributes.address, falling back to the id's part after the network
    prefix ("base_0x..."). None when the item carries neither."""
    addr = (item.get("attributes") or {}).get("address")
    if addr:
        return addr
    pid = item.get("id") or ""
    return pid.split("_", 1)[1] if "_" in pid else None


def parse_payload(payload, page):
    """-> [(address, rank, row)] for one page, rows without ts/sources/ranks."""
    inc = _included(payload)
    out = []
    for i, item in enumerate(payload.get("data") or []):
        addr = pool_address(item)
        if not addr:
            print(f"WARN page {page} item {i}: no pool address, not written")
            continue
        rel = item.get("relationships") or {}
        ids = {k: _rel_id(rel, k) for k in ("base_token", "quote_token", "dex")}
        out.append((addr, (page - 1) * PAGE_SIZE + i + 1, {
            "pool": addr,
            "attributes": item.get("attributes"),
            "relationships": ids,
            "base_token_attr": inc.get(("token", ids["base_token"])),
            "quote_token_attr": inc.get(("token", ids["quote_token"])),
        }))
    return out


def merge(pages, ts):
    """Dedupe pages from every source into one row per pool.

    `pages` is [(source, page, payload)] in fetch order. The first sighting
    supplies attributes; every later one adds its source and its rank. Within
    one source the best (lowest) rank is kept.
    """
    rows, order = {}, []
    for source, page, payload in pages:
        for addr, rank, parsed in parse_payload(payload, page):
            key = addr.lower()
            row = rows.get(key)
            if row is None:
                row = {"ts": ts, "network": NETWORK, "pool": parsed["pool"],
                       "sources": [], "ranks": {},
                       "attributes": parsed["attributes"],
                       "relationships": parsed["relationships"],
                       "base_token_attr": parsed["base_token_attr"],
                       "quote_token_attr": parsed["quote_token_attr"]}
                rows[key] = row
                order.append(key)
            if source not in row["sources"]:
                row["sources"].append(source)
            if source not in row["ranks"] or rank < row["ranks"][source]:
                row["ranks"][source] = rank
    return [rows[k] for k in order]


def latest_row(row):
    """The dashboard copy: these fields only, as-is, null when missing."""
    a = row.get("attributes") or {}
    bt = row.get("base_token_attr") or {}
    return {
        "pool": row.get("pool"),
        "sources": row.get("sources"),
        "base_token_address": bt.get("address"),
        "base_token_symbol": bt.get("symbol"),
        "base_token_name": bt.get("name"),
        "dex_id": (row.get("relationships") or {}).get("dex"),
        "base_token_price_usd": a.get("base_token_price_usd"),
        "reserve_in_usd": a.get("reserve_in_usd"),
        "fdv_usd": a.get("fdv_usd"),
        "market_cap_usd": a.get("market_cap_usd"),
        "volume_usd_h24": (a.get("volume_usd") or {}).get("h24"),
        "transactions_h24": (a.get("transactions") or {}).get("h24"),
        "price_change_percentage_h24": (a.get("price_change_percentage") or {}).get("h24"),
        "pool_created_at": a.get("pool_created_at"),
    }


# ------------------------------------------------------------- writing

def write_rows(path, rows):
    # "x": a run's file is never rewritten. A second run in the same second
    # fails loudly instead of replacing the first.
    with gzip.open(path, "xt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")


def write_json(path, obj, indent=None):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=indent, separators=None if indent else (",", ":"))
        fh.write("\n")
    os.replace(tmp, path)


def main(out_dir=OUT_DIR, now=None):
    start = time.monotonic()
    now = now or datetime.now(timezone.utc)
    ts = now.isoformat(timespec="seconds")
    calls = universe_calls()

    pages, errors, ok = [], {}, 0
    for n, (source, page, path) in enumerate(calls):
        if n:
            time.sleep(SPACING_S)
        try:
            payload = get(path)
        except Exception as e:
            key = error_key(e)
            errors[key] = errors.get(key, 0) + 1
            print(f"WARN {path}: {type(e).__name__}: {e}")
            continue
        ok += 1
        pages.append((source, page, payload if isinstance(payload, dict) else {}))

    rows = merge(pages, ts)
    day = os.path.join(out_dir, now.strftime("%Y-%m-%d"))
    os.makedirs(day, exist_ok=True)
    stem = os.path.join(day, now.strftime("%H%M%S"))

    if ok:
        write_rows(stem + ".jsonl.gz", rows)
        latest = {"generated_at": ts, "network": NETWORK,
                  "pools_written": len(rows),
                  "rows": [latest_row(r) for r in rows]}
        latest_path = os.path.join(out_dir, "latest.json")
        write_json(latest_path, latest)
        size = os.path.getsize(latest_path)
        print(f"latest.json: {size} bytes")
        if size > LATEST_MAX_BYTES:
            print(f"WARN latest.json is over {LATEST_MAX_BYTES} bytes")

    meta = {
        "ts": ts,
        "script_version": script_version(),
        "universe": [{"source": s, "page": p, "path": path} for s, p, path in calls],
        "calls": len(calls),
        "ok": ok,
        "errors": errors,
        "pools_written": len(rows) if ok else 0,
        "duration_s": round(time.monotonic() - start, 1),
    }
    write_json(stem + ".meta.json", meta, indent=2)

    print(f"{ok}/{len(calls)} calls ok, {meta['pools_written']} pools, "
          f"errors {errors or 'none'}")
    if not ok:
        print("every call failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
