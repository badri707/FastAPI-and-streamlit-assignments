# Status — checkpoint (work in progress)

**Phase:** independent evaluation build. Live Skool connection: deferred until approval.

## Done (not yet covered by automated tests)
- Backend core: config (RUN_MODE=evaluation default), SQLite/WAL, Alembic migrations 0001–0002 (incl. FTS5), controllable clock.
- Connector contract, stateful local simulator (separate DB, change feed, fault injection), disabled Skool boundary, mode-enforcing factory.
- Reproducible seed (fixed seed 20260930): 250 members + 12 isolation-group members, 8 courses / 43 lessons, 90 days,
  ~3,460 posts/comments/reactions, scenarios, duplicate/late/out-of-order feed deliveries.
- Synthetic knowledge base (49 docs incl. deliberate contradictions, text PDF, scanned PDF → needs_ocr).
- Incremental idempotent sync (deferred orphans resolve; 0 remaining after full sync).
- Deterministic metrics, support inbox rules, AI answer pipeline (local Ollama + Qwen3-4B-Instruct-2507 Q4_K_M),
  owner chat tools, durable jobs/worker, actions (draft→approve→send→verify, reconciliation), automation rules,
  backup/restore, retention, reports/CSV (formula-injection safe), import with preview, auth/security, most API routers.

## Known incomplete
- `app/main.py` imports routers not yet written: learning_api, reports_api, data_api, lab_api → app does not start yet.
- Frontend, scripts (setup/start/stop/doctor/check/backup/restore), docs, tests, AI eval, measurements: not started.

## Open question to owner
- Message interrupted: "More than 3000 members of the…" — likely request to scale the synthetic community to 3,000+. Awaiting confirmation.

## Next executable step
Write the four missing routers, then `cd backend && uv run python -m app.evaluation --yes` and start the API.
