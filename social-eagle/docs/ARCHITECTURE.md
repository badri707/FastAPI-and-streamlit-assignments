# Architecture and data model

## Processes (all local, loopback-only)

```
scripts/start ─► supervisor (app.supervisor, one per data dir, file lock)
                  ├─ API: uvicorn app.main:app on 127.0.0.1:8787  — serves /api/* and the built React UI (same origin)
                  └─ worker: app.worker (single instance, file lock) — durable DB jobs, scheduling, heartbeat
Ollama (separate local service, 127.0.0.1:11434) — one inference at a time, bounded context (4096)
```

The supervisor restarts a crashed API/worker with backoff (gives up after 5 crashes in 10 minutes and reports
"degraded"). `scripts/stop` signals only the supervisor whose pid file and command line match this project.

## Layers

| Layer | Module | Notes |
|---|---|---|
| Connector contract | `connectors/base.py` | Change feed with cursors, thread lookup, writes with idempotency keys, explicit `UnsupportedOperation`, typed errors (auth expired, unavailable, rate limited, timeout-unknown-outcome). Every adapter declares source, mode, operations, coverage notes. |
| Evaluation adapter | `connectors/simulator.py` | Stateful simulator in its own SQLite file (`data/simulator.db`): members, posts/comments/replies, reactions, courses/lessons, progress, assignments, events, attendance, leaderboard snapshots, synthetic sessions, DMs, member actions, change log, fault injection, write log. |
| Skool boundary | `connectors/skool.py` | Refuses construction unless `RUN_MODE=live` AND `LIVE_CONNECTION_AUTHORIZED=true`, and still raises (not implemented). |
| Import adapter | `services/importer.py` | CSV/JSON with mapping preview, schema checks, provenance, own group + dataset label. |
| Persistence | `models.py`, Alembic | SQLite, WAL, foreign keys, busy timeout, short transactions, FTS5 (`knowledge_fts`, `posts_fts`). |
| Sync | `services/sync.py` | Incremental, idempotent, one commit per page, deferred orphans, late-event-safe progress, failures recorded as failures. |
| Analytics | `services/metrics.py` | Defined metrics, IST day boundaries, staff/bot separation, coverage notes. |
| Retrieval | `services/knowledge.py` | Versioned docs, chunking, hybrid retrieval (FTS5 BM25 + local embeddings, reciprocal rank fusion; keyword-only fallback), tier filtering, restricted matches as metadata only. Embeddings stored in SQLite (`knowledge_embeddings`, float32, L2-normalised). |
| AI | `ai/provider.py`, `ai/answer.py`, `ai/policy.py`, `ai/chat.py` | Provider interface + Ollama adapter, breaker, structured output, deterministic pre/post policy, owner-chat tools. |
| Workflows | `services/jobs.py`, `actions.py`, `automation.py`, `handlers.py`, `worker.py` | Durable jobs, dedupe keys, leases, retries, expiry, publish→verify→reconcile, rules with quiet hours/limits. |
| API/UI | `api/*`, `frontend/` | Session auth + CSRF, validated request bodies, React screens. |

## Data model (main tables)

- `groups` (source, upstream_id) → everything is group-scoped. `members` unique (group_id, upstream_id); `member_tags`, `member_notes`.
- `posts` (post/comment/reply; parent_id, root_id; version, edited_at, deleted_at; client_ref for our own writes), `reactions`.
- `courses` (synthetic access_tiers), `lessons`, `lesson_completions` (current state + `state_at`), `progress_events` (append-only),
  `assignments`, `submissions` (status, reviewer feedback — separate from completion).
- `events`, `event_registrations`, `event_attendance` (duration nullable = unknown), `leaderboard_snapshots`, `session_events` (SYNTHETIC only).
- `support_items` (status, label + label_source, human_verified, first_response_at/by, resolved_at).
- `knowledge_docs` (doc_key + version, sha256, access_tiers, status incl. needs_ocr/superseded), `knowledge_chunks`.
- `ai_runs` (model, digest, policy version, prompt SHA-256 only, retrieved chunk refs + versions, output, status, latency).
- `jobs` (UNIQUE dedupe_key, lease_owner/lease_expires_at, attempts, run_after, expires_at), `actions` (UNIQUE idempotency_key,
  state machine, simulated, delivery_target, approval, remote_id), `action_attempts`, `automation_rules`, `segments`.
- `settings` (pause, thresholds, clock, AI modes, dataset selection, retention), `sync_state`, `sync_deferred`, `worker_heartbeats`,
  `users`, `user_sessions`, `import_batches`, `audit_log`, `notifications`, `chat_messages`.

Every synced row stores `dataset` (`synthetic` or `import:<id>`) and observation timestamps.

## Clocks
- Scheduling/date logic uses `app.clock.now()` — wall time + offset (evaluation) or frozen (tests); shared via the settings table.
- Job leases use real wall time, so advancing the test clock never steals a live worker's lease.

## Upgrade paths (documented, NOT implemented)
See `docs/UPGRADE_PLAN.md`: server database (PostgreSQL via SQLAlchemy URL + migration review), paid AI provider behind
`LLMProvider`, hosted deployment (TLS, secrets manager, auth hardening), live Skool adapter behind `CommunityAdapter`.
