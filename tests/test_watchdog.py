"""watchdog.py's staleness rule for the Base log.

check_staleness is pure, so `now` is placed either side of the threshold
rather than waited for.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

import watchdog as W

NOW = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)


def ago(**kw):
    return (NOW - timedelta(**kw)).isoformat()


def kinds(problems):
    return [p["kind"] for p in problems]


def test_fresh_is_no_problem():
    assert W.check_staleness(ago(minutes=50), NOW) == []


def test_exactly_three_hours_is_still_fresh():
    assert W.check_staleness(ago(hours=3), NOW) == []


def test_one_second_over_three_hours_is_stale():
    assert kinds(W.check_staleness(ago(hours=3, seconds=1), NOW)) == ["stale"]


def test_missing_and_unreadable():
    assert kinds(W.check_staleness(None, NOW)) == ["missing"]
    assert kinds(W.check_staleness("not a time", NOW)) == ["unreadable"]


def test_future_beyond_tolerance_is_flagged():
    future = (NOW + timedelta(minutes=6)).isoformat()
    assert kinds(W.check_staleness(future, NOW)) == ["ahead"]
    near = (NOW + timedelta(minutes=4)).isoformat()
    assert W.check_staleness(near, NOW) == []


def test_override_zero_forces_the_alert():
    assert kinds(W.check_staleness(ago(seconds=1), NOW, max_age_s=0)) == ["stale"]


@pytest.mark.parametrize("raw,want", [(None, None), ("", None), (" 0 ", 0),
                                      ("90", 5400)])
def test_parse_max_age_minutes(raw, want):
    assert W.parse_max_age_minutes(raw) == want


@pytest.mark.parametrize("raw", ["-1", "1.5", "soon"])
def test_parse_max_age_minutes_rejects(raw):
    with pytest.raises(ValueError):
        W.parse_max_age_minutes(raw)


def write_meta(root, day, stem, ts, pools_written):
    d = root / day
    d.mkdir(parents=True, exist_ok=True)
    (d / (stem + ".meta.json")).write_text(
        json.dumps({"ts": ts, "pools_written": pools_written}))


def test_newest_meta_ts_reads_the_newest_file(tmp_path):
    write_meta(tmp_path, "2026-10-20", "230000", "old", 5)
    write_meta(tmp_path, "2026-10-21", "010000", "mid", 5)
    write_meta(tmp_path, "2026-10-21", "110000", "new", 5)
    assert W.newest_meta_ts(str(tmp_path / "*" / "*.meta.json")) == "new"


def test_newest_meta_ts_skips_all_fail_and_unreadable_runs(tmp_path):
    write_meta(tmp_path, "2026-10-21", "080000", "good", 7)
    write_meta(tmp_path, "2026-10-21", "090000", "failed", 0)
    (tmp_path / "2026-10-21" / "100000.meta.json").write_text("{not json")
    assert W.newest_meta_ts(str(tmp_path / "*" / "*.meta.json")) == "good"


def test_newest_meta_ts_none_when_no_files(tmp_path):
    assert W.newest_meta_ts(str(tmp_path / "*" / "*.meta.json")) is None


def test_newest_meta_ts_none_when_every_run_failed(tmp_path):
    write_meta(tmp_path, "2026-10-21", "090000", "failed", 0)
    assert W.newest_meta_ts(str(tmp_path / "*" / "*.meta.json")) is None


def test_all_fail_runs_do_not_reset_the_clock(tmp_path, monkeypatch):
    # newest meta wrote nothing; the last good one is over 3h old -> stale
    monkeypatch.chdir(tmp_path)
    base = tmp_path / "data" / "base"
    write_meta(base, "2026-10-21", "085900", ago(hours=3, minutes=1), 12)
    write_meta(base, "2026-10-21", "115000", ago(minutes=10), 0)
    out = tmp_path / "STALE.txt"
    assert W.main(["--out", str(out), "--now", NOW.isoformat()]) == 0
    assert "over the 3h 0m limit" in out.read_text()
    assert kinds(W.check_staleness(W.newest_meta_ts(), NOW)) == ["stale"]


def test_main_writes_and_removes_the_alert_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "STALE.txt"
    assert W.main(["--out", str(out), "--now", NOW.isoformat()]) == 0
    assert "no meta file with pools_written > 0" in out.read_text()
    write_meta(tmp_path / "data" / "base", "2026-10-21", "115000",
               ago(minutes=10), 3)
    assert W.main(["--out", str(out), "--now", NOW.isoformat()]) == 0
    assert not out.exists()


def test_main_rejects_bad_override():
    assert W.main(["--max-age-minutes", "x"]) == 2
