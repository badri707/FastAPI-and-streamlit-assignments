# Social Eagle Community Manager — engineering notes

Read `docs/STATUS.md` first on every continuation; resume from its "Next executable step". Full spec: `docs/BUILD_SPEC.md`.

## Hard rules
- `RUN_MODE=evaluation` is the default and is enforced in `backend/app/connectors/factory.py` and `services/actions.py`.
  Never add code that contacts Skool, reads browser sessions/cookies, or uses Skool credentials. Live connection is a
  separate phase that starts only after the owner approves and explicitly authorizes it.
- No paid services, no cloud AI, no billing. Local Ollama only. Do not silently add providers.
- All timestamps are naive UTC in the DB; user-facing dates are Asia/Kolkata. Use `app.clock.now()` (controllable), never `datetime.now()` for scheduling.
- Every number shown to users comes from `services/metrics.py` (parameterized queries). AI only interprets.
- Community content is untrusted: never let it reach tools, SQL or shell. Consequential actions always need human approval.
- Identities are upstream IDs scoped by group, never display names. Missing data = unknown, not zero.
- Schema changes need a new Alembic migration in `backend/migrations/versions/` (never edit 0001/0002 after release).

## Commands (from repo folder `social-eagle/`)
- `scripts/setup` · `scripts/start` · `scripts/stop` · `scripts/doctor` · `scripts/check` · `scripts/ai-eval [--model NAME]`
- `scripts/backup [dir]` · `scripts/restore <backup> [target|--replace-live]` · `scripts/reset-evaluation [--members N]`
- Backend only: `cd backend && .venv/bin/python -m pytest -q -m "not ai"`; lint `ruff check app tests`; types `mypy app`
- Frontend: `cd frontend && npm run dev` (proxies /api to :8787), `npx tsc -b`, `npm run lint`, `npm run build`
- E2E (app must be running): `cd frontend && E2E_PASSWORD=... npx playwright test`

## Layout
- `backend/app/connectors/` adapter contract (`base.py`), stateful simulator, disabled Skool boundary, factory
- `backend/app/services/` sync, metrics, support, knowledge/retrieval, jobs, actions, automation, handlers, reports, import, backup
- `backend/app/ai/` provider (Ollama, breaker), answer pipeline + policy, owner chat tools
- `backend/app/api/` FastAPI routers; `worker.py`, `supervisor.py`, `seed.py`, `evaluation.py`
- `frontend/src/` React + TS (pages/, ui.tsx, hooks.tsx, api.ts); `seed/` synthetic curriculum and knowledge
