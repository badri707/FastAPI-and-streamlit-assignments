# Acceptance matrix — independent application

Status legend: **PASS** = check ran and passed on the date in `docs/VERIFICATION_REPORT.md`; **MEASURED** = quantified, not a pass/fail
gate; **PARTIAL** = works with stated limitation; **DEFERRED** = live Skool phase (not a failure of this phase).

| # | Requirement (spec §) | Check | Evidence | Status |
|---|---|---|---|---|
| 1 | Reproducible install, migrations, startup, build, types, lint, tests (§11) | `scripts/setup`, `scripts/start`, `scripts/check` | VERIFICATION_REPORT §1 | PASS |
| 2 | Known-fixture analytics incl. IST boundaries, missing data, duplicates, group isolation (§11) | `tests/test_metrics_fixture.py` (hand-computed expectations) | pytest | PASS |
| 3 | Seeded samples reconcile with source records (§11) | `test_seed_reconciles_with_source_records` | pytest | PASS |
| 4 | Connection failures / expired session not shown as empty community (§11) | `test_partial_sync_and_auth_expiry_are_not_an_empty_community`; UI banner | pytest, Lab | PASS |
| 5 | Member search, filters, notes, progress, support queue, reports, chat, pause, settings via UI (§11) | Playwright walkthrough (6 flows) + API tests | `docs/evidence/e2e-results.json`, screenshots | PASS |
| 6 | AI evaluation ≥30 cases: answerable, unanswerable, conflicting, restricted, analytics, injection; held-out paraphrases (§11) | `scripts/ai-eval` (44 cases) + held-out set (18 cases) with the real local model | `docs/evidence/ai-eval-*.json` | MEASURED (see report) |
| 7 | Release gate: unauthorized actions, cross-member/course disclosure, invented metrics, duplicate external actions must fail (§11) | consequential-approval test; restricted cases; number verification; duplicate tests | pytest + AI eval safety categories | PASS (0 safety failures in final runs — see report) |
| 8 | Restart, double-launch, timeout-after-send, partial sync, model outage, low disk, missing SSD, sleep/wake (§11) | `test_actions_jobs.py`, `test_backup_import_resilience.py`, `test_second_worker_process_exits_due_to_lock`, demo step 4 | pytest, demo.json | PASS (controlled fault injection, labelled) |
| 9 | Consistent backup + restore into separate DB without altering running data (§11) | `test_backup_during_writes_and_restore_to_separate_dir`; UI "Test restore" | pytest | PASS |
| 10 | Measure response time, memory, queue behaviour, representative workload (§11) | `tests/perf/measure.py` | `docs/evidence/perf.json` | MEASURED (container, not the Mac) |
| 11 | Evaluation mode cannot initialise live connector / contact Skool / send externally even with credentials (§11) | `test_mode_isolation.py` network spy | pytest | PASS |
| 12 | Demo: new question → grounded answer → published → restart worker → no duplicate → progress change → report changes (§11) | `tests/demo/run_demo.py` against the running app | `docs/evidence/demo.json` | PASS (see report) |
| 13 | Persistent evaluation indicator; simulated delivery labelled in records and exports (§3) | UI banner; `actions.simulated`; CSV header | screenshots, `test_csv_export_neutralises_formulas` | PASS |
| 14 | Stateful simulator with controls: question, progress, reaction, event join, time, faults (§3) | Evaluation lab + `/api/lab/*` | e2e, pytest | PASS |
| 15 | Seed: ~250 members (scaled to 3,200 at owner's request), 8 courses, 90 days, ≥2,000 interactions, scenarios (§3) | `app/seed.py`; scenario tests | reset output; `test_named_scenarios` | PASS |
| 16 | Optional CSV/JSON import with preview, schema checks, provenance, no mixing (§3) | `test_import_preview_commit_isolation_and_duplicate` | pytest | PASS |
| 17 | Auth, protected sessions, first-run enrollment, CSRF/origin/host checks, no default creds (§9) | `test_api_security.py` | pytest | PASS |
| 18 | Knowledge ingestion: Markdown, text, text PDF, transcripts; scanned PDF detected (§7) | `test_pdf_text_and_scanned_detection_and_versions` | pytest | PASS |
| 19 | Untrusted content cannot override policy (§7) | injection precheck tests; AI eval injection cases | pytest, AI eval | PASS |
| 20 | Structured-output validation, timeouts, retries, circuit breaker; model outage = genuine unavailable state (§4, §7) | provider tests; `test_ai_outage_keeps_deterministic_features_working` | pytest | PASS |
| 21 | Durable jobs: dedupe, leases, retries, expiry/catch-up, graceful shutdown (§8) | `test_job_dedupe_and_exclusive_leases`, expiry test | pytest | PASS |
| 22 | Pause switch stops new external actions and explains in-progress ones (§8) | `test_pause_*`, e2e pause flow | pytest, e2e | PASS |
| 23 | Scripts: setup/start/stop/doctor/check/backup/restore/seed/reset (§12) | executed in build container | VERIFICATION_REPORT §1 | PASS (Linux container; macOS run pending on owner's Mac) |
| 24 | Time-spent from synthetic sessions + unavailable case (§6) | `test_late_progress_event_does_not_override_and_time_spent_rules` | pytest | PASS |
| 25 | Tamil/Tanglish handling (§5) | not evaluated — no approved material in those languages | — | NOT EVALUATED |
| 26 | Live Skool connector and live checks (§13) | — | — | DEFERRED until approval |
