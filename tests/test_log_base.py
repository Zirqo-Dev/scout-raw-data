"""log_base.py: parsing, dedupe, the files a run writes, and failure paths.

get() is replaced by a fake that serves fixtures, and time.sleep by a
recorder, so no test waits or touches the network.
"""
import gzip
import io
import json
import os
import shutil
import subprocess
import urllib.error
from datetime import datetime, timezone

import pytest

import log_base as L
from conftest import load_fixture

NOW = datetime(2026, 10, 21, 14, 5, 9, tzinfo=timezone.utc)
TS = "2026-10-21T14:05:09+00:00"

PAGE1 = {"trending": "trending_p1.json", "top_volume": "top_volume_p1.json",
         "new": "new_p1.json"}

ROW_KEYS = {"ts", "network", "pool", "sources", "ranks", "attributes",
            "relationships", "base_token_attr", "quote_token_attr"}
META_KEYS = {"ts", "script_version", "universe", "calls", "ok", "errors",
             "pools_written", "duration_s"}
LATEST_ROW_KEYS = {"pool", "sources", "base_token_address",
                   "base_token_symbol", "base_token_name", "dex_id",
                   "base_token_price_usd", "reserve_in_usd", "fdv_usd",
                   "market_cap_usd", "volume_usd_h24", "transactions_h24",
                   "price_change_percentage_h24", "pool_created_at"}


def addr(tag):
    return "0x" + tag.rjust(40, "0")


def fixture_get(path):
    """Page 1 of each source from its fixture, later pages empty."""
    for source, page, p in L.universe_calls():
        if p == path:
            return load_fixture(PAGE1[source]) if page == 1 else {"data": []}
    raise AssertionError("unexpected path %s" % path)


def http_error(code):
    return urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(b""))


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(L.time, "sleep", calls.append)
    return calls


@pytest.fixture
def run(tmp_path, monkeypatch, sleeps):
    """Run main() against fixtures into tmp_path; -> (exit code, out dir)."""
    def _run(get=fixture_get):
        monkeypatch.setattr(L, "get", get)
        out = tmp_path / "base"
        return L.main(out_dir=str(out), now=NOW), out
    return _run


def read_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def merged():
    pages = [(s, 1, load_fixture(f)) for s, f in PAGE1.items()]
    return {r["pool"]: r for r in L.merge(pages, TS)}


# ------------------------------------------------------------- universe

def test_universe_is_the_twelve_documented_calls():
    inc = "&include=base_token,quote_token,dex"
    want = ([f"/networks/base/trending_pools?page={i}{inc}" for i in range(1, 6)]
            + [f"/networks/base/pools?page={i}&sort=h24_volume_usd_desc{inc}"
               for i in range(1, 6)]
            + [f"/networks/base/new_pools?page={i}{inc}" for i in range(1, 3)])
    assert [p for _, _, p in L.universe_calls()] == want


# ------------------------------------------------------------- parsing

def test_parse_payload_keeps_attributes_and_token_objects_verbatim():
    payload = load_fixture("trending_p1.json")
    out = L.parse_payload(payload, 1)
    assert [(a, r) for a, r, _ in out] == [(addr("b01"), 1), (addr("b02"), 2)]
    _, _, row = out[0]
    assert row["attributes"] == payload["data"][0]["attributes"]
    assert row["relationships"] == {"base_token": "base_" + addr("a01"),
                                    "quote_token": "base_" + addr("e0"),
                                    "dex": "uniswap_v3"}
    assert row["base_token_attr"] == payload["included"][0]["attributes"]
    assert row["quote_token_attr"] == payload["included"][1]["attributes"]


def test_rank_counts_from_the_page_offset():
    out = L.parse_payload(load_fixture("trending_p1.json"), 3)
    assert [r for _, r, _ in out] == [41, 42]


def test_missing_included_gives_null_token_attrs():
    row = merged()[addr("b04")]
    assert row["base_token_attr"] is None and row["quote_token_attr"] is None


def test_address_falls_back_to_id():
    item = {"id": "base_" + addr("b09"), "attributes": {}}
    assert L.pool_address(item) == addr("b09")
    assert L.pool_address({"attributes": {}}) is None


# ------------------------------------------------------------- dedupe

def test_dedupe_keeps_every_source_and_rank():
    rows = merged()
    assert len(rows) == 4
    a, b = rows[addr("b01")], rows[addr("b02")]
    assert a["sources"] == ["trending", "new"]
    assert a["ranks"] == {"trending": 1, "new": 2}
    assert b["sources"] == ["trending", "top_volume"]
    assert b["ranks"] == {"trending": 2, "top_volume": 1}
    # first sighting supplies the attributes; later ones are not mixed in
    assert b["attributes"]["reserve_in_usd"] == "45678.9"
    assert set(a) == ROW_KEYS and a["ts"] == TS and a["network"] == "base"


def test_dedupe_ignores_address_case_and_keeps_best_rank_in_a_source():
    p = load_fixture("trending_p1.json")
    upper = json.loads(json.dumps(p))
    upper["data"][1]["attributes"]["address"] = addr("b01").upper().replace("0X", "0x")
    rows = L.merge([("trending", 2, p), ("trending", 1, upper)], TS)
    # page 2 holds b01 at 21 and b02 at 22; page 1 holds b01 at 1 and again,
    # upper-cased, at 2. One row each, b01 at its best rank.
    assert len(rows) == 2
    first = next(r for r in rows if r["pool"].lower() == addr("b01"))
    assert first["ranks"] == {"trending": 1}
    assert first["sources"] == ["trending"]


# ------------------------------------------------------------- a full run

def test_run_writes_gz_meta_and_latest(run):
    code, out = run()
    assert code == 0
    day = out / "2026-10-21"
    rows = read_gz(day / "140509.jsonl.gz")
    assert len(rows) == 4 and all(set(r) == ROW_KEYS for r in rows)

    meta = json.loads((day / "140509.meta.json").read_text())
    assert set(meta) == META_KEYS
    assert meta["ts"] == TS
    assert meta["calls"] == 12 and meta["ok"] == 12 and meta["errors"] == {}
    assert meta["pools_written"] == 4
    assert [u["path"] for u in meta["universe"]] == [p for _, _, p in L.universe_calls()]
    assert meta["script_version"] == L.script_version()

    latest = json.loads((out / "latest.json").read_text())
    assert set(latest) == {"generated_at", "network", "pools_written", "rows"}
    assert latest["generated_at"] == TS and latest["pools_written"] == 4


def test_latest_rows_hold_only_the_listed_fields_copied_as_is(run):
    _, out = run()
    latest = json.loads((out / "latest.json").read_text())
    rows = {r["pool"]: r for r in latest["rows"]}
    assert all(set(r) == LATEST_ROW_KEYS for r in rows.values())
    a = rows[addr("b01")]
    assert a == {
        "pool": addr("b01"), "sources": ["trending", "new"],
        "base_token_address": addr("a01"), "base_token_symbol": "AAA",
        "base_token_name": "Synthetic A", "dex_id": "uniswap_v3",
        "base_token_price_usd": "1.2345", "reserve_in_usd": "45678.9",
        "fdv_usd": "1234567.8", "market_cap_usd": None,
        "volume_usd_h24": "34567.8",
        "transactions_h24": {"buys": 410, "sells": 380, "buyers": 120, "sellers": 95},
        "price_change_percentage_h24": "-5.6",
        "pool_created_at": "2026-10-20T08:00:00Z"}
    d = rows[addr("b04")]
    assert d["dex_id"] == "uniswap_v4"
    assert all(d[k] is None for k in LATEST_ROW_KEYS - {"pool", "sources", "dex_id"})


def test_latest_stays_under_200kb_at_full_universe():
    # 12 pages of 20, no overlap: the most rows a run can produce.
    item = load_fixture("trending_p1.json")["data"][0]
    tok = load_fixture("trending_p1.json")["included"][0]
    tok["attributes"]["name"] = "N" * 60
    pages = []
    for n in range(12):
        data = []
        for i in range(20):
            it = json.loads(json.dumps(item))
            it["attributes"]["address"] = addr("f%03d%02d" % (n, i))
            data.append(it)
        pages.append(("trending", n + 1, {"data": data, "included": [tok]}))
    rows = L.merge(pages, TS)
    assert len(rows) == 240
    body = json.dumps({"generated_at": TS, "network": "base", "pools_written": 240,
                       "rows": [L.latest_row(r) for r in rows]},
                      separators=(",", ":"))
    assert len(body.encode()) < L.LATEST_MAX_BYTES


def test_calls_are_spaced(run, sleeps):
    run()
    assert sleeps == [2.5] * 11


def test_a_run_file_is_never_rewritten(run):
    run()
    with pytest.raises(FileExistsError):
        run()


def test_partial_failure_is_recorded_and_exits_zero(run):
    def flaky(path):
        if "new_pools" in path:
            raise http_error(429)
        return fixture_get(path)
    code, out = run(flaky)
    meta = json.loads((out / "2026-10-21" / "140509.meta.json").read_text())
    assert code == 0
    assert meta["ok"] == 10 and meta["errors"] == {"429": 2}
    assert meta["pools_written"] == 3


# ------------------------------------------------------------- all fail

def test_all_fail_writes_meta_and_exits_one(run):
    def down(path):
        raise http_error(503)
    code, out = run(down)
    assert code == 1
    day = out / "2026-10-21"
    meta = json.loads((day / "140509.meta.json").read_text())
    assert set(meta) == META_KEYS
    assert meta["ok"] == 0 and meta["calls"] == 12
    assert meta["errors"] == {"503": 12} and meta["pools_written"] == 0
    assert not (day / "140509.jsonl.gz").exists()
    assert not (out / "latest.json").exists()


def test_network_errors_are_counted_by_class(run):
    def offline(path):
        raise urllib.error.URLError("no route")
    code, out = run(offline)
    meta = json.loads((out / "2026-10-21" / "140509.meta.json").read_text())
    assert code == 1 and meta["errors"] == {"URLError": 12}


# ------------------------------------------------------------- get()

class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def scripted_urlopen(monkeypatch, script):
    seen = []

    def urlopen(req, timeout):
        seen.append(req.full_url)
        step = script.pop(0)
        if isinstance(step, int):
            raise http_error(step)
        return FakeResponse(json.dumps(step).encode())
    monkeypatch.setattr(L.urllib.request, "urlopen", urlopen)
    return seen


def test_get_retries_5xx_and_429_with_backoff(monkeypatch, sleeps):
    seen = scripted_urlopen(monkeypatch, [502, 429, {"data": []}])
    assert L.get("/x") == {"data": []}
    assert sleeps == [20, 40]
    assert seen == [L.BASE + "/x"] * 3


def test_get_does_not_retry_4xx(monkeypatch, sleeps):
    scripted_urlopen(monkeypatch, [404])
    with pytest.raises(urllib.error.HTTPError):
        L.get("/x")
    assert sleeps == []


def test_get_raises_after_last_try(monkeypatch, sleeps):
    scripted_urlopen(monkeypatch, [503, 503, 503, 503])
    with pytest.raises(urllib.error.HTTPError) as e:
        L.get("/x")
    assert e.value.code == 503 and sleeps == [20, 40, 60]


# ------------------------------------------------------------- version

@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_script_version_matches_git_hash_object():
    out = subprocess.run(["git", "hash-object", L.__file__],
                         capture_output=True, text=True, check=True)
    assert L.script_version() == out.stdout.strip()
