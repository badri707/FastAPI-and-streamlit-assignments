# Upgrade plan (documented, not implemented)

These paths are kept open by the interfaces; none is implemented or "zero effort".

1. **Live Skool adapter** — implement `CommunityAdapter` in `connectors/skool.py` after explicit authorization (see
   `docs/SKOOL_ADAPTER_PLAN.md`). Use a separate database (`live-app.db` is already selected when `RUN_MODE=live`).
2. **Paid/hosted AI provider** — add a class implementing `LLMProvider` (`chat_json`, `health`) in `ai/provider.py`, select via
   `AI_PROVIDER`. Requires: owner approval of cost, a data-processing review (member data would leave the machine), key storage in a
   secret store, re-running `scripts/ai-eval`.
3. **Server database** — SQLAlchemy models are portable; switch the URL to PostgreSQL, replace SQLite-specific pieces (FTS5 virtual
   tables → PostgreSQL full-text search or a search service, `INSERT … ON CONFLICT` dialect, `UPDATE … RETURNING` lease query is
   supported), run migrations on a copy, migrate data with a script, load-test.
4. **Always-on hosting** — required for 24/7 operation. Needs TLS, a real auth provider or hardened passwords + MFA, secrets manager,
   process supervision (systemd/containers), backups to durable storage, monitoring/alerting, and a security review before any
   public exposure. Until then, operation is local and stops when the Mac sleeps.
5. **More workers** — job leasing is already multi-worker safe; SQLite write concurrency is the limit (move to PostgreSQL first).
