# Permissions, automation tiers and data handling

## Who can do what
- **One local admin role.** Created via a one-time enrollment token (`data/enrollment.token`, mode 600, deleted after use). No default credentials.
- Sessions: random token in an HttpOnly, SameSite=Strict cookie (only its SHA-256 is stored), 12-hour expiry, CSRF token required
  on every unsafe request, Host allow-list (DNS-rebinding protection), Origin check, login rate limit (5/minute), CSP + frame denial.
- The service binds to 127.0.0.1 only; the supervisor and `app.main.run` refuse other addresses in this phase.

## Automation tiers (enforced in the backend)
| Tier | Examples | Behaviour |
|---|---|---|
| 1. Read/report automatically | sync, metrics, search, summaries, task preparation | Always on |
| 2. Draft initially | replies, reminders, onboarding messages, moderation suggestions | Draft → human review |
| 3. Automatic permitted actions | allow-listed FAQ replies (`mode=auto` rules) | Only `reply` rules; only when the answer is grounded, cited, numerically verified, not conflicting/restricted/support/billing; within hourly/daily limits and outside quiet hours; global pause respected; **in this phase only against the local simulator** |
| 4. Explicit approval | ban/remove, delete, refund, billing/permission changes, bulk outbound messages | Never automatic (`approve()` rejects rule approval); bulk messages expand only after a human approves |

The model's self-reported confidence is never used as permission. Auto-publish eligibility is computed by deterministic checks.

## Evaluation-mode isolation
- `connectors/factory.get_adapter()` returns only the simulator in evaluation mode; requesting `skool` raises `ModeViolation`.
- `SkoolAdapter` refuses construction unless `RUN_MODE=live` **and** `LIVE_CONNECTION_AUTHORIZED=true`, and then still raises (not implemented).
- `actions.execute_action()` refuses any action not marked `simulated` with `delivery_target=local-simulator` in evaluation mode.
- Skool credentials in the environment are never read. Verified by `tests/test_mode_isolation.py` (network spy).

## Untrusted content
Posts, comments, imported files and retrieved passages are data. They are wrapped as UNTRUSTED in prompts, cannot select tools, and
deterministic pre-checks block prompt-injection / privilege-escalation patterns before any model call. Output is checked for
personal data (emails/phones), configuration leakage, invented numbers and invalid citations. A member claiming to be an admin
gains nothing.

## Data handled and where
| Data | Where | Retention |
|---|---|---|
| Synthetic community (evaluation) | `data/simulator.db`, `data/app.db` | until reset |
| Optional imports | `data/app.db` (own group, `import:<id>` label); upload staged in `data/imports/` until commit | until deleted from the Import page |
| AI runs | prompt **SHA-256 only**, retrieved chunk ids/versions, output, model digest, policy version | 90 days (configurable) |
| Audit log | `data/app.db` | 365 days (configurable) |
| Owner chat history | `data/app.db` | 90 days (configurable) |
| Backups | `data/backups/` (mode 700) or configured `BACKUP_DIR` | manual |

Per-member export (`GET /api/members/{id}/export`) and local erasure (`POST /api/members/{id}/erase`, survives re-sync) are available.
**Model processing:** Ollama runs on this machine; prompts never leave it. `OLLAMA_NO_CLOUD=1` is recommended (the variable exists in
Ollama v0.40.6's configuration). No cloud AI provider is configured.

## Secrets
`.env` (mode 600, git-ignored) holds configuration only. No Skool secrets are used in this phase. Logs do not record request bodies
or passwords. Data, logs, backups and `.env` are excluded by `.gitignore`.
