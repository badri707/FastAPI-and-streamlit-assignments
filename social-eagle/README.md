# Social Eagle Community Manager

A local community-management application for the Social Eagle Skool community: member directory, support inbox,
evidence-grounded AI answers, learning/event/engagement reports, owner chat, and controlled automation.

> **Current phase: independent evaluation.** The app runs against a **stateful local community simulator** with a
> reproducible **synthetic** community (3,200 fictional members, 8 fictional courses, 90 days of history). Everything else —
> database, sync, analytics, retrieval, local AI, worker, workflows and UI — is real. **No Skool account, URL, login or data is
> used. Live Skool connection is deferred until you approve this application and explicitly authorize that phase.**

## What it does
- **Overview** — members, participation trends, unanswered questions, pending actions, connection/worker/AI health.
- **Members** — search/filter, tags, internal notes, evidence-linked activity, progress, support items, follow-ups; saved segments with
  transparent, editable rules ("no observed contributions" is not "inactive").
- **Support inbox** — questions that appear unanswered (observed fact), labels with their source (rule/manual), assign, resolve
  (human-verified), staff replies, AI drafts, repeated-question topics.
- **AI answers** — retrieves approved course material (respecting the member's tier), asks the local model for a cited answer,
  then checks citations, numbers, personal data, conflicts and restricted material. It abstains, asks for clarification or routes to
  staff instead of guessing.
- **Learning & events** — marked-complete progress (not proof of viewing), stalled learners, next lesson within tier, assignments and
  reviewer feedback, registration vs attendance vs duration (unknown is not zero).
- **Engagement & reports** — defined metrics, IST day boundaries, comparisons, response/resolution times, daily/weekly summaries,
  CSV exports with scope and coverage notes.
- **Owner chat** — ask questions in plain English; the model picks a read-only tool, numbers come from calculated metrics and are
  verified before you see them.
- **Automation** — rules with triggers, conditions, quiet hours (IST), limits and expiry; review queue; action history showing
  drafted/approved/sent/verified; global pause; consequential actions always need your approval.
- **Operations** — durable jobs and worker with heartbeat, backups with verified restore, optional CSV/JSON import, settings,
  diagnostics, and an **Evaluation lab** to inject events (questions, progress, reactions, event joins, time travel, connector faults).

## Limitations (honest list)
- Synthetic data only; simulator results are **not** proof that Skool exposes the same data or actions.
- Runs only while your Mac is awake and the app is started — **not** a 24/7 service.
- Local AI quality is limited: see measured results in `docs/VERIFICATION_REPORT.md`. Keep a human in the loop.
- Exact time online is not measured (synthetic session events are used only to validate the calculation).
- No billing/membership-payment data; refunds/billing always go to staff.
- Tamil/Tanglish handling has not been evaluated.

## Requirements (all free)
macOS (Apple Silicon) · Python 3.12 via [uv](https://docs.astral.sh/uv/) · Node.js 20+ · [Ollama](https://ollama.com) with one model
(see `docs/AI_MODEL.md`). About 4 GB of disk for the model and a few hundred MB for the app and data.

## Setup and daily use
```bash
cd social-eagle
scripts/setup            # installs locked dependencies, migrates, builds the UI, seeds the synthetic community (~3 min)
scripts/start            # starts API + worker, prints http://127.0.0.1:8787/ and (first run) a one-time enrollment token
scripts/stop             # stops only this project's processes
scripts/doctor           # environment and health report
scripts/backup           # consistent backup now (nightly backups run automatically while the app is running)
scripts/restore <backup> # verify a backup by restoring it into a separate folder
scripts/reset-evaluation # discard evaluation changes and re-seed (asks you to type RESET; keeps your admin account)
scripts/check            # lint, types, tests, frontend build
scripts/ai-eval          # real-model evaluation set (writes docs/evidence/ai-eval-*.json)
```
First visit: paste the enrollment token, choose a username and a password (10+ characters). There are no default credentials.

A guided tour with example questions and expected results: **`docs/APPROVAL_WALKTHROUGH.md`**.

## Documentation
| Doc | Contents |
|---|---|
| `docs/STATUS.md` | Progress, evidence, blockers, next step |
| `docs/VERIFICATION_REPORT.md` | Commands, results, measurements, AI evaluation |
| `docs/ACCEPTANCE_MATRIX.md` | Feature → acceptance check → evidence |
| `docs/CAPABILITIES.md` | Independent vs live verification per feature |
| `docs/ARCHITECTURE.md` | Processes, layers, data model |
| `docs/METRICS.md` | Metric definitions |
| `docs/PERMISSIONS.md` | Roles, automation tiers, isolation, data handling |
| `docs/AI_MODEL.md` | Model choice, provenance, Mac setup |
| `docs/BACKUP_RESTORE.md`, `docs/TROUBLESHOOTING.md`, `docs/UPGRADE_PLAN.md`, `docs/SKOOL_ADAPTER_PLAN.md` | Operations and future work |
| `docs/BUILD_SPEC.md` | The full build specification |
