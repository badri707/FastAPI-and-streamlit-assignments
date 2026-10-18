# Status

**Independent application verified; live Skool connection deferred until approval.** (2026-10-18)

## Done
- **Build plan:** all six milestones from the spec are complete; see `docs/ACCEPTANCE_MATRIX.md`.
- **Synthetic community:** scaled to **3,200 members** at the owner's request.
- **Results:** checks, tests, the browser walkthrough, the required demo, the AI evaluation and performance measurements are in
  `docs/VERIFICATION_REPORT.md`.
- **Evidence:** in `docs/evidence/` (JSON results and screenshots, synthetic data only).

## Not done / open
- **On the Mac:** re-measure performance and AI on the MacBook Air M2 (container numbers are not Mac numbers), and verify the
  scripts there (only Linux was exercised).
- **Tamil/Tanglish:** not evaluated.
- **Membership/billing reporting:** not implemented (no source data).
- **Live Skool adapter:** deferred until the owner approves and explicitly authorizes connection (`docs/SKOOL_ADAPTER_PLAN.md`).

## Next executable step
Owner review: on the Mac, run `scripts/setup && scripts/start` and follow `docs/APPROVAL_WALKTHROUGH.md`.
Then optionally run `scripts/ai-eval` and `cd backend && .venv/bin/python -m tests.perf.measure --password <yours>` to get Mac numbers.

## Resume notes for development
- Read `CLAUDE.md` first.
- Schema changes need migration 0004+.
- Keep `RUN_MODE=evaluation` until the owner authorizes the live phase.
