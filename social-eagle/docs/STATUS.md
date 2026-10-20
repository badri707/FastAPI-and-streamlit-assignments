# STATUS — Social Eagle Community Manager

Last updated: **2026-10-20** (session 1). Branch: `claude/social-eagle-skool-bot-7nnj0i`. Project folder: `social-eagle/`.

## Headline (evidence-backed)

| Clause | State | Evidence |
|---|---|---|
| Public Skool reads verified | **NOT VERIFIED — blocked in build environment** | The cloud sandbox's network policy refused `www.skool.com` and `help.skool.com` (proxy 403). See `docs/verification/public-read-attempt-2026-10-20.txt`. The connector is implemented and its safety behaviour is tested with a mock transport, but it has **never read a real Skool page**. |
| Local workflows verified | **Yes, for the section 1A reporting core** | 51/51 automated tests pass; lint and type check clean (`docs/verification/check-2026-10-20.txt`). All 12 business scenarios pass on clearly labelled synthetic data. |
| Private integration | **Deferred** (by design) | Private mode raises `PrivateModeDisabled` in the DB layer, connector registry and web layer (tested). |

So the accurate phrase today is: **"Local workflows verified; public Skool reads implemented but unverified; private integration deferred."** Do not say "public reads verified" until step 1 below passes.

## What works (verified by tests or a real run)

- **Data model**: normalized SQLite schema (communities, members and name history, cohorts and memberships, plan-label history, courses and lessons, entitlements, enrolments, lesson deadlines, progress snapshots, posts, comments, content versions, reactions, assignments, submissions, feedback, wins, support questions and events, leaderboard snapshots, sync runs, report runs, jobs, outbox, audit log). Each record has provenance: source ref, mode, method, field origin, observed time, precision, displayed value, hash, parser version and sync run. Alembic migration; a test checks that the migration matches the models.
- **Validated import adapter** (`app/connectors/importer.py`): stable-ID dedupe, edit versioning, explicit deletions and like removals only, failed syncs ingest nothing, renamed members keep their identity, duplicate display names stay separate people, workspace isolation (synthetic data is refused in public mode, non-synthetic data is refused in test mode, private mode is refused).
- **Metrics** (`app/analytics/metrics.py`), checked against an independent calculator working on the raw fixture: participation (posts, comments, likes given and likes received kept separate; staff and bots excluded), 7/30-day active days, learning (only comparable snapshots, unknown stays unknown, no overdue for optional, unreleased or not-entitled lessons, grace period for new joiners, alumni don't inherit current-batch deadlines), assignments (submitted, reviewed, feedback delivered and result are separate facts), wins (self-reported), support (first staff response, peer and bot responses counted separately, an acknowledgement is not resolution, reopen handling, awaiting-member versus awaiting-staff, target breaches with calendar or working-hours basis), leaderboard (partial snapshots labelled), outreach and staff follow-ups (transparent rules, no score).
- **Daily report engine** (`app/reports/daily.py`): exact IST interval with UTC bounds, cutoff, data health, section availability. A degraded report is issued when a source fails; an unavailable report when everything fails. Values are withheld, never shown as zero. Re-running with the same data returns the existing report. Late data creates a new revision that supersedes the old one, and old revisions stay unchanged. Outputs are HTML, JSON, summary CSV and follow-ups CSV, with CSV formula-injection protection.
- **Scheduler and worker** (`app/worker/`): durable job table with unique dedupe keys, atomic lease claims, recovery from expired leases, bounded queue, backoff, and a failed-job list. Daily planning at 09:00 IST, restart-safe. Sleep/wake produces labelled catch-up reports plus `missed_run` events. Runs older than 7 days are recorded as `expired_run` instead of being generated in a burst. A pause switch holds delivery. The outbox tracks delivery state separately from report generation (in-app only).
- **Member evidence export**: dated timeline of the member's actions next to the company's responses, coverage gaps and the corrections audit trail. Other learners are never named (tested).
- **Permission-scoped lesson search** (FTS5): a General member cannot retrieve VIP-only lessons (tested).
- **Public connector safety** (mock transport): https plus host allowlist, every redirect re-validated, robots.txt honoured, no cookie or auth headers even when `SKOOL_*` env vars exist, login walls, 403s and parse failures become failed syncs, refresh doesn't duplicate records, all write methods raise. In test mode no HTTP request leaves the process (network spy).
- **Web dashboard** (FastAPI with server-rendered pages): overview, members (search, filter, pagination), member detail (timeline, notes, corrections with audit), learning, participation, assignments, wins, support plus outreach, leaderboard, data health (sync runs, queue, scheduler events, heartbeat), reports (Run now, Preview, history, JSON and CSV downloads), search, settings (pause, import). Loopback-only Host check, token login, signed HttpOnly SameSite=Strict cookie, Origin check on POST, CSP. A real-browser run found that `Referrer-Policy: no-referrer` blocked logins (Chrome sent `Origin: null`); this was fixed and a regression test added.
- **Operations scripts**: `setup`, `start` (web and worker, port-conflict check, prints the URL), `stop` (only this project's PIDs), `doctor`, `check`, `backup` (SQLite online backup API plus sha256), `restore` (into a separate folder, integrity check, refuses live paths, detects checksum mismatch), `seed-evaluation` and `reset-evaluation` (synthetic DB only, `--yes` required to discard).
- **Real run in the sandbox**: setup, seed, start, a live public read attempt (recorded as a failed sync) and screenshots of the UI with synthetic data (`docs/screenshots/`).

## What is simulated

- All Social Eagle members, batches, plan labels (General/Annual/VIP), courses, progress, assignments, questions and staff responses are **fictional** (`app/fixtures.py`). Access rules, deadlines, the 24-hour response target and the 7-day grace period are **demonstration values, not company policy**.
- Fault injection (HTTP 503, total outage) is simulated in the fixture and labelled.
- The public-page parser was tested only against a **hand-written structural fixture** (`tests/fixtures/public_group_structure_SYNTHETIC.html`). The `__NEXT_DATA__` / `postTrees` field names are an unverified assumption about Skool's markup.

## What remains unverified or not built

| Item | State |
|---|---|
| Live public Skool read and parser accuracy | Unverified (network blocked). Next step 1. |
| Official Skool doc definitions (points from likes received, daily activity in UTC, course permissions) | Taken from the spec's 2026-10-20 review; **not re-verified** this session (help.skool.com blocked). |
| React + TypeScript + Vite frontend | **Not built.** A server-rendered Jinja UI was used to deliver the reporting core first. This is a deliberate deviation awaiting your approval; the JSON API exists for a later React client. |
| Local AI (Ollama), owner chat, reply drafts, question routing (spec sections 5 and 7A), AI eval cases | **Not started** (milestone 5). No AI output exists anywhere; nothing is faked. |
| Capacity benchmark (10k members / 100k events), Locust harness, `CAPACITY_PLAN.md`, `PERFORMANCE_REPORT.md` | **Not started.** No capacity claims are made. |
| PostgreSQL option | Not started. |
| Events/attendance, onboarding segments, automation rules screen | Not started. |
| Email/Sheets delivery adapters | Not started (blocked by design until authorized). |
| macOS-specific script testing (spaces in path, Apple Silicon) | Scripts quote all paths but were run only on Linux in the sandbox. Run `scripts/doctor.sh` on the Mac. |

## Next executable steps (resume here)

1. **On your Mac** (where skool.com is reachable): `cd social-eagle && scripts/setup.sh && uv run python -m app.cli public-sync`. If it fails with `ParseFailed`, open the cached HTML in `data/public_cache/` and update `parse_group_page` in `app/connectors/public_skool.py`. Then save a dated, permitted snapshot as a regression fixture, record the result in `docs/PUBLIC_SOURCES.md` and `docs/CAPABILITIES.md`, and only then mark "public reads verified".
   (Alternatively, allow `www.skool.com` and `help.skool.com` in this cloud environment's network settings so a later session can verify.)
2. Re-verify the 7 Skool help articles listed in `docs/SKOOL_WORKFLOWS.md` and update definitions if they changed.
3. Milestone 4 remainder: public course/event/leaderboard metadata where visible; data-health alerts in the overview.
4. Milestone 5: Ollama adapter (check RAM before choosing a model), source-grounded search/chat, offline reply drafts, question register states from section 7A, 30+ AI evaluation cases.
5. Milestone 6: React/Vite frontend if approved, load harness and capacity report, PostgreSQL option.

## Commands

```bash
cd social-eagle
scripts/setup.sh                 # install deps (uv), migrate, create admin token
scripts/seed-evaluation.sh       # load synthetic scenarios (add --yes to reset an existing test workspace)
scripts/start.sh                 # web + worker; prints http://127.0.0.1:8765
scripts/check.sh                 # ruff + mypy + pytest
scripts/backup.sh && scripts/restore.sh data/backups/test-<stamp>.db
scripts/stop.sh
```
