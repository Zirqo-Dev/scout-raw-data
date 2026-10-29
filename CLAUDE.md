# scout-raw-data: rules for Claude Code

This repo is PUBLIC. Everything in it, including data/, is world-readable.

## Roles
- The owner decides. Claude chat reviews and writes prompts. You are the only writer.
- Never write the owner's name, handles, emails or wallets into this repo; say 'the owner'.

## Git rules
- HOLD BEFORE COMMIT: show diff stat and test results, then wait for the owner's explicit "commit".
- Commit to main only. Never push other branches or tags. On a 403, report the exact error and stop. Do not look for a workaround.
- log.yml pushes to main about every hour. Pull with rebase before working. Never commit files under data/ by hand.
- A pull with --autostash unstages staged work. Re-stage and re-verify the content before committing.
- Never force-push or rewrite history.
- Commit messages: short imperative subject; keep the attribution lines you were given.

## Secrets
- Secrets live only in GitHub Actions secrets. None are needed now: GeckoTerminal's public API takes no key. Never write a secret into a file, URL, log line, issue or report.

## Raw only
- This repo logs what GeckoTerminal returns and nothing else. No scoring, tiers, filters, derived fields, holders, dashboard or hypotheses. Dedupe by pool address is the only processing.
- No trading advice anywhere (code, docs, reports).
- Contract address, not ticker. Never invent or guess an address. Mark anything unverified as UNVERIFIED. Test fixtures use synthetic addresses only.
- UNIVERSE in scripts/log_base.py changes only with the owner's approval and a dated line in docs/CHANGES.md. Every meta file records the universe it ran with.
- Data collected here is exploratory. It is never evidence for a hypothesis registered later, in this repo or in any other repo.

## Workflows
- log.yml is started by cron-job.org via workflow_dispatch, hourly. Do not add a GitHub schedule to it without the owner's approval.
- watchdog.yml carries the only GitHub schedule ("41 * * * *"), deliberately: a slow backstop that shares nothing with cron-job.org.
- The watchdog counts a run as fresh only if its meta file has pools_written > 0.
- Keep permissions minimal per workflow. Pass workflow inputs through env, never interpolate ${{ }} into run: blocks.

## Tests
- Run `python -m pytest -q` before every report. Report the pass count. Tests use fixtures only, never the network.
- test.yml is an alarm, not a gate. It runs only on pushes touching scripts/, tests/, requirements-test.txt or itself.

## Reports
- 15 lines or fewer unless the owner asks for detail.
- Lead with the outcome. Then: diff stat, test count, decisions needing the owner, anything unverified.
- State what you did NOT verify. Do not repeat the steps you took.
- Point to a file path for long output instead of pasting it.
