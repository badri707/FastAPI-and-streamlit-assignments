# Capabilities — independent verification vs. future Skool verification

"Verified in local simulator" means: implemented, exercised against the stateful local simulator with synthetic data, and covered by
the automated tests or the UI walkthrough listed in `docs/ACCEPTANCE_MATRIX.md`. It is **not** evidence of Skool compatibility.
Every live column entry is **Deferred until approval** — no Skool access was requested or used in this phase.

| Capability | Independent application (this phase) | Live Skool verification |
|---|---|---|
| Member directory, search, filters, tags, internal notes | Verified in local simulator | Deferred until approval |
| Member detail with evidence-linked activity history | Verified in local simulator | Deferred until approval |
| Saved segments with editable thresholds (new, no observed contributions, pending onboarding, needs attention, stalled, silent learners) | Verified in local simulator | Deferred until approval |
| Incremental sync: pagination, cursors, duplicates, late/out-of-order events, edits, deletions, rejoins | Verified in local simulator | Deferred until approval (real feed availability unknown) |
| Connector failures shown as failures (auth expired, outage, partial sync, rate limit) | Verified with controlled fault injection | Deferred until approval |
| Posts/comments/replies/reactions ingestion, nested threads | Verified in local simulator | Deferred until approval |
| Support inbox: unanswered detection, labels with source, assign, resolve (human-verified), staff replies | Verified in local simulator | Deferred until approval |
| Repeated-question topics (deterministic) + AI topic summary | Verified in local simulator (AI summary = suggestion) | Deferred until approval |
| Knowledge ingestion (Markdown/text/transcripts/text PDF), versions, scanned-PDF detection (needs OCR) | Verified locally | Not applicable to Skool |
| Evidence-grounded AI answers with citations, abstain/clarify/conflict/restricted handling | Verified with real local model on the synthetic evaluation set (see VERIFICATION_REPORT.md for measured pass rate and failures) | Deferred until approval |
| Automatic FAQ replies (evaluation rule) published to the thread with verification | Verified in local simulator | Deferred until approval — Skool write interface unverified |
| Drafts, edit, approve, reject, review queue, action history (drafted/approved/sent/verified) | Verified in local simulator | Deferred until approval |
| Durable jobs: dedupe, leases, retries, expiry after downtime, worker restart, double launch | Verified locally | Not applicable |
| Timeout-after-send reconciliation, no duplicate replies | Verified in local simulator (simulator supports idempotency-key lookup) | Deferred — real platform may not support lookups; would fall back to thread matching or hold for review |
| Global pause; consequential-action approval; quiet hours; limits | Verified locally | Deferred until approval |
| Courses/lessons, marked-complete progress, stalled rules, next lesson within tier | Verified in local simulator | Deferred until approval |
| Assignments, submissions, reviewer feedback | Verified in local simulator | Deferred — availability unknown |
| Events: registration vs attendance vs duration (unknown ≠ 0) | Verified in local simulator | Deferred — availability unknown |
| Leaderboard points/levels and changes | Verified in local simulator (synthetic model, labelled) | Deferred — real values only after verification |
| Time spent from session events (+ unavailable case) | Verified with SYNTHETIC session events only | Deferred — very likely unavailable from Skool |
| Contributions, trends, comparisons, response/resolution times, daily/weekly summaries | Verified with known-answer fixtures | Deferred until approval |
| CSV exports with scope/coverage notes and formula-injection protection | Verified locally | Not applicable |
| Owner chat over structured, read-only tools with number verification | Verified with real local model on analytics cases (measured) | Deferred until approval |
| Membership/billing reporting | Not implemented (no source data); refunds/billing always routed to staff | Deferred — depends on role/plan |
| Optional CSV/JSON import with mapping preview, provenance, isolation, delete | Verified locally | Not applicable |
| Auth, CSRF, host/origin checks, rate limiting, input validation | Verified locally | Not applicable |
| Backup (online API) + verified restore into separate directory | Verified locally | Not applicable |
| Evaluation-mode isolation (no live connector, no external network) | Verified with network spy | Not applicable |
| Tamil/Tanglish handling | Not evaluated (no approved material in those languages) | Deferred |
