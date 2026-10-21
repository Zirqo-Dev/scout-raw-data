#!/usr/bin/env python3
"""Notice when the Base log stalls, without depending on the thing that runs it.

log.yml is started by cron-job.org calling workflow_dispatch. If that job
stops, or its token expires, data/base simply stops advancing and nothing in
the repository notices. This script is what notices: it reads the ts of the
newest meta file that wrote pools off disk and reports whether it is too old.
It never writes to the data, never commits and never calls an API.

A run counts as fresh only if its meta file has pools_written > 0. All-fail
runs still commit their meta file, but they do not reset the clock, so a
GeckoTerminal outage alerts after MAX_AGE_S just as a stopped dispatcher does.

Copied from hoodscout-data's scripts/watchdog.py, cut down to one feed.
check_staleness() is pure: a timestamp in, problems out.
"""
import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone

META_GLOB = "data/base/*/*.meta.json"
FEED = "base log"

# Hourly dispatch, so three hours is two missed runs plus slack.
MAX_AGE_S = 3 * 60 * 60

# A timestamp this far ahead of now is a clock or data fault, not freshness.
# Without this a bad clock would read as permanently fresh.
FUTURE_TOLERANCE_S = 5 * 60


def parse_ts(value):
    """-> an aware datetime, or None if it is missing or not a timestamp."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_max_age_minutes(raw):
    """-> a threshold override in seconds, or None for no override.

    Empty means no override, which is what a scheduled run passes. Anything
    else must be a whole number of minutes >= 0; a bad value raises, because
    an operator proving the alert path who mistyped it needs to be told. 0
    forces the alert at any positive age.
    """
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        minutes = int(raw)
    except ValueError:
        raise ValueError("max-age-minutes must be a whole number of minutes, "
                         "got %r" % raw)
    if minutes < 0:
        raise ValueError("max-age-minutes cannot be negative, got %d" % minutes)
    return minutes * 60


def human(seconds):
    if seconds is None:
        return "unknown"
    seconds = int(seconds)
    sign = "-" if seconds < 0 else ""
    h, m = divmod(abs(seconds) // 60, 60)
    return "%s%dh %dm" % (sign, h, m) if h else "%s%dm" % (sign, m)


def check_staleness(value, now, max_age_s=None):
    """-> a list of problems (at most one); empty means fresh.

    Kinds: `missing` (no meta file with pools), `unreadable` (a value that is not a
    timestamp), `ahead` (in the future past the tolerance) and `stale`
    (older than the threshold).
    """
    limit = MAX_AGE_S if max_age_s is None else max_age_s
    if value is None:
        return [{"kind": "missing", "age_s": None, "limit_s": limit,
                 "message": "%s: no meta file with pools_written > 0" % FEED}]
    dt = parse_ts(value)
    if dt is None:
        return [{"kind": "unreadable", "age_s": None, "limit_s": limit,
                 "message": "%s: timestamp is not readable (%r)"
                            % (FEED, str(value)[:64])}]
    age = (now - dt).total_seconds()
    if age < -FUTURE_TOLERANCE_S:
        return [{"kind": "ahead", "age_s": age, "limit_s": limit,
                 "message": "%s: timestamp is %s in the future (%s)"
                            % (FEED, human(-age), value)}]
    if age > limit:
        return [{"kind": "stale", "age_s": age, "limit_s": limit,
                 "message": "%s: %s old, over the %s limit (%s)"
                            % (FEED, human(age), human(limit), value)}]
    return []


def newest_meta_ts(pattern=META_GLOB):
    """-> the ts of the newest meta file with pools_written > 0, or None.

    Paths sort chronologically (YYYY-MM-DD/HHMMSS.meta.json), so they are
    read newest first until one wrote pools. A meta file that is unreadable,
    or records an all-fail run, is skipped: it is not evidence the log is
    alive.
    """
    for path in sorted(glob.glob(pattern), reverse=True):
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        written = d.get("pools_written")
        if isinstance(written, int) and not isinstance(written, bool) and written > 0:
            return d.get("ts")
    return None


def render(problems, now, max_age_s=None):
    """The issue body. One line per problem, plus when it was checked."""
    lines = ["The Base log has gone quiet. Checked at %s."
             % now.isoformat(timespec="seconds"), ""]
    lines += ["- %s" % p["message"] for p in problems]
    if max_age_s is not None:
        lines += ["",
                  "**THIS IS A TEST RUN.** The threshold was overridden to %s "
                  "by a manual dispatch, so this alert says nothing about "
                  "whether the log is actually stale." % human(max_age_s)]
    lines += ["",
              "Threshold: %s." % human(MAX_AGE_S if max_age_s is None else max_age_s),
              "",
              "log.yml is started by cron-job.org calling workflow_dispatch. "
              "Check that job first, then the token expiry. This check runs "
              "on GitHub's own schedule and is deliberately independent of it."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", metavar="PATH", default=None,
                    help="write the issue body here IF there are problems, "
                         "and remove any stale copy if there are none")
    ap.add_argument("--now", metavar="TS", default=None,
                    help="override the clock, for a dry run")
    ap.add_argument("--max-age-minutes", metavar="N", default=None,
                    help="override the threshold, in minutes, to prove the "
                         "alert path. Empty means no override; 0 forces it.")
    a = ap.parse_args(argv)

    now = parse_ts(a.now) if a.now else datetime.now(timezone.utc)
    if now is None:
        print("--now is not a readable timestamp: %r" % a.now)
        return 2
    try:
        max_age_s = parse_max_age_minutes(a.max_age_minutes)
    except ValueError as e:
        print("bad --max-age-minutes: %s" % e)
        return 2

    ts = newest_meta_ts()
    problems = check_staleness(ts, now, max_age_s)
    print("checked at %s" % now.isoformat(timespec="seconds"))
    print("  newest good meta ts: %s" % (ts or "MISSING"))
    if max_age_s is not None:
        print("  OVERRIDE: threshold set to %s (test run)" % human(max_age_s))
    for p in problems:
        print("  %s" % p["message"])
    if not problems:
        print("no problems: the log is inside its threshold")

    if a.out:
        if problems:
            with open(a.out, "w", encoding="utf-8") as fh:
                fh.write(render(problems, now, max_age_s))
            print("wrote %s" % a.out)
        elif os.path.exists(a.out):
            os.remove(a.out)
    # Always 0: the workflow acts on the presence of --out, and a non-zero
    # exit would make a real alert look like a broken script.
    return 0


if __name__ == "__main__":
    sys.exit(main())
