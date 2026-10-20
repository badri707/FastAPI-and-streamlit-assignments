# CLAUDE.md — Social Eagle Community Manager

On continuation: read `docs/STATUS.md` first and resume from "Next executable steps". Do not re-scaffold. Full spec: `docs/BUILD_SPEC.md`.

## Commands (run from `social-eagle/`)
- Install: `uv sync --python 3.12` · Checks: `scripts/check.sh` (ruff, mypy, pytest)
- Single test: `uv run pytest tests/test_scenarios.py::test_s6_unanswered_question_overdue`
- Run: `scripts/start.sh` / `scripts/stop.sh` · Seed synthetic: `scripts/seed-evaluation.sh --yes`
- New migration after model change: `uv run alembic revision --autogenerate -m "..."` (the `test_migrations_match_models` test fails until you do)

## Hard rules
- Public mode: logged-out GET reads of allowlisted Skool hosts only. Never add write methods, auth, cookies, stealth, or private endpoints.
- Private mode stays disabled (`PrivateModeDisabled`) until the owner explicitly authorizes it.
- Synthetic data only in `test.db`; public data never labelled as Social Eagle data.
- Missing data is `unknown`/`unavailable`, never 0. Don't infer time online, watch time, or resolution from replies.
- Never remove assertions or swallow exceptions to make tests pass. Update `docs/STATUS.md` and `docs/CAPABILITIES.md` with evidence when capability status changes.
- All timestamps stored naive UTC; reports presented in Asia/Kolkata with UTC bounds.
