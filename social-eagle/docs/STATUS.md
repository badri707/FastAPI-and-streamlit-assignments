# STATUS — Social Eagle Community Manager

Last updated: **2026-10-21** (session 2). Branch: `claude/social-eagle-skool-bot-7nnj0i`. Project folder: `social-eagle/`.

## Headline (evidence-backed)

| Clause | State | Evidence |
|---|---|---|
| Public Skool reads verified | **NOT VERIFIED — blocked in build environment** | The cloud sandbox's network policy refused `www.skool.com` and `help.skool.com` (proxy 403). See `docs/verification/public-read-attempt-2026-10-20.txt`. The connector is implemented and its safety behaviour is tested with a mock transport, but it has **never read a real Skool page**. |
| Local workflows verified | **Yes, for the section 1A reporting core** | 51/51 automated tests pass; lint and type check clean (`docs/verification/check-2026-10-20.txt`). All 12 business scenarios pass on clearly labelled synthetic data. |
| Private integration | **Deferred** (by design) | Private mode raises `PrivateModeDisabled` in the DB layer, connector registry and web layer (tested). |

So the accurate phrase today is: **"Local workflows verified; public Skool reads implemented but unverified; private integration deferred."** Do not say "public reads verified" until step 1 below passes.

## Update 2026-10-21 (later) — main prototype: simulated community + working bot
The owner asked for an "exact main prototype" before any private access. Built, in the **test workspace only**:
- **Community simulator** (`/community`): a Skool-style feed and threads where you act as any fictional member or staff (`Acting as`) to post, comment, reply, like, confirm "solved" or reopen. Every action goes through the validated importer as a `local_sim` capture, so reports, member timelines and data health update from it. Nothing is sent to Skool.
- **Bot engine** (`app/bot/engine.py`, spec 7A): rule-based question detection (labelled `rule_based`), permission-scoped retrieval (lessons the asker is entitled to plus owner-approved answers), and these routes:
  - answer with citations
  - one clarification, then resume when the member replies
  - escalate to the owner for refunds, billing, deadline extensions, exceptions, complaints, explicit human requests, no supporting material, or a reopen after a bot answer
  - owner inbox (`/bot`): answer, assign, defer, close; optionally save the answer as approved knowledge, which the bot then reuses
- **Answer generation** (`app/bot/ai.py`): a real Ollama adapter (loopback only, JSON output validated, citations must refer to the given sources, circuit breaker). When no model is running, an **extractive** mode quotes course text verbatim and labels it "quoted, not AI-generated". **No local model has been run yet**: Ollama isn't installable in the cloud sandbox. The AI path is tested only with a mocked HTTP endpoint.
- **Reports and metrics**: new evidence state `answered_unconfirmed` (an answer is not resolution). Sources may now be covered by several consecutive captures. A day still in progress shows as `in_progress` (partial), not complete. The worker extends coverage for the live simulator and runs the bot every tick in test mode. The pause switch stops bot actions.
- 75 tests pass (21 new). Verified in a real Chromium run with screenshots `docs/screenshots/bot_answer_thread.png`, `bot_owner_inbox.png` and `community_feed.png`.

**Simulated / unverified:** all people and threads are fictional; question detection is a keyword rule, not AI; AI answer quality is **not measured** (needs Ollama on the Mac); the bot has never posted to Skool and cannot.

**Next for the prototype:** on the Mac, `brew install ollama && ollama pull llama3.2:3b` (check its license and RAM use first). The bot page will then show `ai:llama3.2:3b`. Run the AI evaluation set (30+ cases) and record answer quality.

## Update 2026-10-21 — first live read on the owner's Mac
- `public-sync` reached https://www.skool.com/ai-automation-society logged-out (no login wall). It printed `success new=0 changed=0`.
- The owner ran `public-inspect --full` (keys and types only). The real page matches the parser's expected structure: `pageProps.postTrees[33].post.{id,name,metadata{title,content,upvotes,comments,...},createdAt,labelId,user{...}}` and `currentGroup.{id,name,metadata{displayName,totalMembers,totalOnlineMembers,...},labels[]}`.
- Likely explanation for `new=0`: the background worker's own public refresh, which runs right after `start.sh`, had already ingested the posts. A repeat read correctly found no new records. **Awaiting confirmation** from the owner's `public.db` counts (sqlite3 query in chat). Public reads are not marked verified until then.
- Fixes: post categories now come from `currentGroup.labels[]` via `labelId`. A category change is no longer counted as an edit. A read that recognises zero posts is now a `ParseFailed` failure rather than a success.
- Privacy: the page's user objects contain fields such as email, bio, social links and location. The parser stores **only** the user id and display name.

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
