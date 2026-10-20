# Capabilities and acceptance matrix

Statuses: **verified public read** · **verified local workflow** · **import only** · **private access deferred** · **unavailable** · **not tested** · **not built**.
Evidence date for everything below: 2026-10-20. Scope: this repository on the cloud build sandbox (Linux, Python 3.12). Test names refer to `social-eagle/tests/`.

## Feature matrix

| Feature | Public read | Local workflow (test mode) | Private integration | Evidence |
|---|---|---|---|---|
| Public group page → posts, authors, displayed totals | **not tested live** (network blocked); parser tested on a synthetic structural fixture | n/a | deferred | `test_connectors.py::test_public_page_becomes_records_and_refresh_does_not_duplicate`; `verification/public-read-attempt-2026-10-20.txt` |
| Refresh without duplicate records | mock-verified | verified | deferred | same test; `test_s10_*` |
| Login wall / 403 / parse failure → failed sync (never empty) | mock-verified | n/a | deferred | `test_login_wall_and_denials_are_failures_not_empty`, `test_parse_failure_is_reported` |
| URL allowlist, redirect validation, robots.txt, no credentials | mock-verified | n/a | deferred | `test_unsafe_urls_rejected`, `test_redirect_to_other_host_rejected`, `test_robots_disallow_respected` |
| External writes (post/reply/react/message/join) | **disabled** (raises) | disabled (local only) | deferred | `test_writes_disabled_in_every_mode` |
| Test mode makes zero Skool requests | n/a | verified (network spy) | n/a | `test_test_mode_sends_no_network_requests` |
| Workspace isolation (public / test / private) | verified | verified | deferred (raises) | `test_workspace_isolation` |
| Member directory, search, filters, notes, corrections with audit | observed contributors only (incomplete by definition) | verified | deferred | `test_web.py::test_member_detail_notes_corrections_evidence` |
| Batch / plan label / entitlement / enrolment history | unavailable from public pages | verified (import only) | deferred | `test_s3_*`, `test_s4_*`, `test_s5_*` |
| Course progress (recorded completion, comparable changes, unknown) | unavailable from public pages | verified (import only) | deferred | `test_s1_*`, `test_s2_*`, `test_s9_*` |
| Assigned-lesson deadlines (optional, unreleased, not-entitled, grace period, alumni) | unavailable | verified | deferred | `test_s2_*`, `test_s3_*`, `test_s5_*` |
| Participation: posts, comments, likes given and received kept separate, 7/30-day active days | posts only, once live reads work (likes and comments are not enumerated by the public parser) | verified | deferred | `test_report_complete_and_reconciles_with_raw_records`, `test_ist_midnight_boundary` |
| Assignments: submitted / reviewed / feedback delivered / result | unavailable | verified | deferred | `test_s8_*` |
| Wins (self-reported) | could map a public "Wins" category later | verified | deferred | report wins section |
| Support: first staff response, peer and bot responses, clarification, reopen, breach | unavailable (needs thread detail) | verified | deferred | `test_s6_*`, `test_s7_*` |
| Leaderboard snapshots (partial labelled) | not tested | verified | deferred | report leaderboard section |
| Daily report: complete / degraded / unavailable, revisions, idempotent | n/a | verified | deferred | `test_s10_*`, `test_s11_*` |
| Scheduler 09:00 IST, restart, catch-up, missed and expired runs | n/a | verified (controllable clock) | n/a | `test_scheduler.py` |
| Durable jobs, leases, double-worker safety, failed-job visibility | n/a | verified | n/a | `test_two_workers_cannot_claim_same_job`, `test_failed_job_is_visible_not_swallowed` |
| Outbox: in-app delivery state, dedupe, pause | n/a | verified | email/Sheets not built | `test_pause_holds_delivery`, `test_s11_*` (one outbox row after a retry) |
| Member evidence export (privacy-scoped) | n/a | verified | deferred | `test_s12_member_export_reconciles_and_is_private` |
| Permission-scoped lesson search (VIP exclusion) | n/a | verified | deferred | `test_s4_*`, `test_lesson_search_permission_scope` |
| CSV formula injection guard, HTML escaping | n/a | verified | n/a | `test_csv_formula_injection_neutralised`, notes XSS check |
| Admin login, loopback Host check, Origin/CSRF check | n/a | verified (also in a real Chromium run) | n/a | `test_requires_login_and_loopback`, `test_null_origin_refused_and_same_origin_allowed` |
| Backup and restore to a separate location, checksum | n/a | verified | n/a | `test_backup_and_restore_into_separate_location` |
| Migrations match models | n/a | verified | n/a | `test_migrations_match_models` |
| Local AI (Ollama), chat, drafts, question routing | **not built** | **not built** | deferred | — |
| Capacity benchmark / load test | **not built** | **not built** | — | — |
| PostgreSQL backend | **not built** | — | — | — |
| React/Vite frontend | **not built** (server-rendered UI instead) | — | — | — |

## The twelve section 1A scenarios (synthetic, local)

| # | Scenario | Result | Test |
|---|---|---|---|
| 1 | Actively learning but quiet member (Anika: 2/6 → 4/6, no posts, not flagged) | pass | `test_s1_quiet_but_learning` |
| 2 | Highly interactive member with little progress (Rahul: 4 posts and many likes, 1/6, two overdue lessons) | pass | `test_s2_interactive_with_little_progress` |
| 3 | Alumnus keeps access, no Batch 2 deadlines (Meera) | pass | `test_s3_alumnus_keeps_access_without_current_deadlines` |
| 4 | VIP course excluded from a General member's expected progress and search (Vikram vs Sana) | pass | `test_s4_vip_course_excluded_for_general_member` |
| 5 | Two enrolments with different deadlines (Priya: DM done, Entrepreneurship lesson 2 overdue) | pass | `test_s5_two_enrolments_different_deadlines` |
| 6 | Unanswered question overdue for staff (Dev, 38 h, breach) | pass | `test_s6_unanswered_question_overdue` |
| 7 | Peer and bot acknowledgement is not resolution (Isha); reopened question (Rahul); awaiting member (Sana) | pass | `test_s7_peer_and_bot_ack_not_resolution` |
| 8 | Assignment submitted, awaiting feedback (Karthik); reviewed but feedback not delivered (Vikram); ambiguous post (Rahul) | pass | `test_s8_assignment_awaiting_feedback` |
| 9 | Missing progress stays unknown (Nila); denominator change → not comparable (Isha) | pass | `test_s9_missing_progress_stays_unknown` |
| 10 | Duplicate import, removed like, edited post, late comment → revision 2; revision 1 unchanged | pass | `test_s10_duplicates_removed_likes_edits_late_records` |
| 11 | Failed sync → degraded report (values withheld) → recovery → revision 2 complete; retry has no duplicate; total outage → unavailable | pass | `test_s11_failed_sync_then_recovery_no_false_inactivity` |
| 12 | Daily report and member export reconcile to raw records; export names no other learners | pass | `test_report_complete_and_reconciles_with_raw_records`, `test_s12_*` |

These pass on **synthetic** data. They demonstrate that the application logic behaves as specified. They do **not** demonstrate production accuracy or that Skool exposes these fields.
