# Social Eagle Community Manager

A local-first monitoring, reporting and support-accountability app for the Social Eagle Skool community. It answers four questions with dated, source-linked evidence: who is participating, what learning progress has been recorded, whose assignments need feedback, and who needs help. It shows missed learner activity and missed company support with equal clarity.

> **Current phase:** local workflows verified on synthetic data. The public Skool reader is implemented but not yet verified against a live page. Private Skool access is deferred until the owner authorizes it. No messages are ever sent to Skool. See `docs/STATUS.md`.

## Features (this release)
- Daily report at 09:00 Asia/Kolkata for the previous day, with **Run now**, **Preview**, ranges, history and revisions. Outputs are HTML, JSON and CSV.
- Separate views for learning, participation, assignments, wins, support and leaderboard, plus data health.
- Members directory and a per-member printable evidence report.
- Three isolated workspaces: **public** (logged-out reads only), **test** (synthetic) and **private** (disabled).
- **Main prototype**: a simulated Skool-style community (test workspace) where you act as fictional members and staff, and **EagleBot** answers questions with citations, asks for clarification, or escalates to the owner inbox.
- Durable worker: restart-safe, catch-up after sleep, missed-run log, pause switch, in-app notification outbox.

## Limitations
Runs only while your Mac is awake. The public reader is not yet verified. There is no AI, chat or reply drafting yet. There is no capacity benchmark yet. The UI is server-rendered rather than React (pending approval). All Social Eagle data in the test workspace is fictional.

## Setup and daily use (macOS, Apple Silicon)
```bash
brew install uv            # once
cd social-eagle
scripts/setup.sh           # installs Python 3.12 deps, migrates DBs, prints admin token (also in data/admin_token)
scripts/seed-evaluation.sh # optional: load synthetic scenarios into the test workspace
scripts/start.sh           # starts web + worker, prints http://127.0.0.1:8765
scripts/doctor.sh          # environment check (RAM, disk, port, DB integrity, optional SSD)
scripts/backup.sh          # consistent SQLite backups → data/backups
scripts/restore.sh data/backups/test-<stamp>.db   # restores into data/restore-eval and verifies
scripts/stop.sh
scripts/check.sh           # lint + type check + tests
```

## Architecture
```
app/connectors/   importer (validated bundles), public_skool (logged-out reader), registry (mode → connector)
app/models.py     normalized SQLAlchemy schema with provenance on every observation
app/analytics/    metric definitions (docs/METRIC_DICTIONARY.md)
app/reports/      daily report engine + member evidence export
app/worker/       durable job queue, scheduler, outbox delivery
app/web/          FastAPI app, auth/security middleware, Jinja templates
migrations/       Alembic
data/             (git-ignored) public.db, test.db, reports, backups, secrets
```
SQLite (WAL, foreign keys) is used, with one database file per mode. The web process and the worker are separate processes and coordinate only through the database.

## Data handling
Data is stored only on this computer, under `data/` (git-ignored). Public mode stores post excerpts, never full profiles. Member exports exclude other learners. To delete everything, stop the app and remove `data/`.

More docs: `docs/STATUS.md`, `docs/CAPABILITIES.md`, `docs/APPROVAL_WALKTHROUGH.md`, `docs/DAILY_REPORT_SPEC.md`, `docs/METRIC_DICTIONARY.md`, `docs/DATA_FEASIBILITY.md`, `docs/PUBLIC_SOURCES.md`, `docs/SKOOL_WORKFLOWS.md`, `docs/BUILD_SPEC.md`.

## Troubleshooting
- *Port in use*: `SE_PORT=8877 scripts/start.sh`.
- *Login fails*: use the token in `data/admin_token`.
- *Public read fails*: see the error on Data health. A login wall or 403 is recorded as a failure, never as an empty community.
- *Report says unavailable*: no source covered that day. Import or sync, then click Run now; a revision will be issued.
