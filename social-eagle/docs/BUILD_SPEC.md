# Social Eagle — Claude Code master build prompt

Build the actual Social Eagle community-management application in this workspace. This is its first operational release, with the same codebase to be enhanced after approval. I need working software, clear documentation and demonstrated results, not just an architecture proposal or an attractive screen.

**Required sequence: build the full independent application, test it against a realistic local community, demonstrate the results for my approval, and only then connect to my real Skool account if I explicitly authorize that later phase. Skool access is not a prerequisite for this build or its independent acceptance tests.**

Act as a careful senior product engineer responsible for implementation, reliability and usability. Inspect, plan, implement, run, test and fix. Explain important decisions in plain English so I understand what we are building. Do not claim universal task coverage, perfect AI accuracy, error-free operation or completed integrations without evidence.

## 1. Fixed context and constraints

- Product: **Social Eagle Community Manager** for my Skool community.
- I have Claude Pro and will use Claude Code for development. Respect its usage limits. Do not assume my subscription includes application API credits, or repurpose my Claude login/session as a generic application API.
- Computer: MacBook Air M2, 8 GB unified RAM, 256 GB internal storage.
- External storage: SanDisk SSD advertised around 2,000 MB/s; capacity, format, mount path and actual throughput are unverified. Do not assume it increases RAM or automatically move data onto it.
- Budget: **zero additional mandatory software, model-API or hosting charges initially**. Existing equipment, internet, power, Skool and Claude subscriptions are outside that incremental budget. Do not enable billing, start paid trials or buy services.
- Time zone: Asia/Kolkata for user-facing dates and schedules; store timestamps in UTC.
- Initial operation is local. Local jobs stop during sleep, shutdown, disconnection or service failure. Explain this visibly; do not advertise 24/7 availability until an always-on deployment has been verified.
- Start in **independent evaluation mode** with synthetic community data, working local AI, real application logic and a stateful local connector. No Skool account, URL, role, API key, login, cookies or export is required.
- Do not request or access my real Skool account before I approve the independent application. Do not inspect existing Skool browser sessions, use any discovered credentials or make live Skool API/browser calls. Missing Skool access is intentional, not a build blocker.
- My eventual Skool role, group plan and integration capabilities are unverified. Evaluate those only in the later authorized connection phase; do not assume they will support every simulated feature.

Proceed with reasonable implementation choices. Ask only for information or authorization needed for the independent build, such as local installation choices or optional model setup. Do not ask premature Skool-access questions. Respect the environment's permission controls; never disable them to get past a failure.

## 2. Start with inspection and an executable plan

1. Read existing project instructions and inspect the current directory and Git state. Preserve existing work. Create a dedicated project folder only if needed; do not overwrite unrelated files.
2. Check architecture, macOS, available RAM, free disk space, Python, Node, package managers, Git, ports and relevant installed tools. Report only needed information; never print secrets or dump the environment.
3. Review current official documentation for the selected dependencies and model provider. Public Skool documentation may inform the future adapter design, but no account connection or access investigation is required now. Record source URLs and access dates. Verify runtime compatibility before choosing versions; commit dependency lockfiles.
4. Create a short milestone plan and a feature-to-acceptance matrix. Then start implementing rather than stopping at the plan.
5. Create the local evaluation environment and deterministic seed dataset immediately. Provide an optional local import interface without requiring me to obtain or supply real Skool data. Do not stop to ask for a community URL, role or credentials.

Keep a concise `CLAUDE.md` for durable commands and rules, a `docs/BUILD_SPEC.md` for this full specification, and `docs/STATUS.md` for completed work, test evidence, blockers and the next executable step. On continuation, read these files and resume without re-scaffolding the application.

## 3. Build independently with a realistic local community

Define a provider-neutral community adapter contract for member data, discussions, progress, events, leaderboards and permitted actions. Implement a **stateful local simulator** against that contract now. It must accept new events, persist state changes and return inspectable results. This simulator is the external community substitute; the actual frontend, backend, database, AI, retrieval, analytics, worker and workflows must all run for real.

Create a reproducible seed dataset with about 250 fictional members, 8 fictional courses, 90 days of timestamped history and at least 2,000 mixed posts/comments/reactions. Include course transcripts/FAQs, completion and assignment records, events, attendance, membership segments and leaderboard snapshots. Use fictional identities and reserved example addresses, not real member information. Keep synthetic entitlements and course policies explicitly separate from actual Social Eagle policies.

Include known scenarios: a new member, a silent learner progressing without commenting, a frequent commenter with low course progress, a member needing support, an unanswered question, an ambiguous question, contradictory lessons, an inaccessible course, duplicate events and late/out-of-order events. Add deterministic fixtures for metrics with known expected answers. Use a controllable clock for repeatable schedule and date-boundary tests; do not make tests depend on the wall clock.

Provide controls to add a question, change lesson progress, add a reaction, join an event, advance test time and inject connector failures. An automatic reply must pass through the real retrieval/model/policy/job pipeline, appear in the local thread and update the action history. A progress event must update the same database and reports used by the application. Do not implement hardcoded dashboards, canned AI replies or buttons that only display success messages.

Use `RUN_MODE=evaluation` by default. Enforce the mode in backend connector construction and action dispatch, not just the UI. Skool connection code must remain inactive even if credentials happen to exist on the machine. External delivery must be impossible in evaluation mode. Show a persistent **Evaluation — synthetic community data** indicator and identify simulated delivery in action records and exported reports.

Maintain `docs/CAPABILITIES.md` with separate columns for independent application verification and future Skool verification. A function can be **verified in the local simulator** while its live connector is **deferred until approval**. That deferred state must not prevent independent acceptance. Do not describe the simulator as verified Skool compatibility.

Provide a validated CSV/JSON import route with mapping previews, schema checks and clear provenance. It is optional, and the synthetic dataset must be sufficient to exercise the full evaluation. Never mix optional real imports with synthetic statistics without explicit selection and clear labeling.

Keep a clean, disabled boundary for the future Skool adapter. Document desired fields/actions and any public-documentation limitations without inventing endpoints, events or availability. Detailed live verification happens only in the later phase below.

## 4. Keep the architecture efficient and upgradeable

Use a small modular application, with these defaults unless inspection finds a concrete compatibility reason to change them:

- **Frontend:** React, TypeScript and Vite; responsive, accessible UI with lightweight styling and charting.
- **Backend:** Python 3.12, FastAPI and validated request/response schemas.
- **Persistence:** SQLite with foreign keys, suitable indexes, WAL on a local filesystem, short transactions, migrations and a supported ORM such as SQLAlchemy/Alembic. Use SQLite FTS5 for initial text retrieval where available.
- **Worker:** one separate Python worker backed by durable database jobs and a process supervisor. No duplicate scheduler inside every web request or development reload.
- **AI:** a provider interface with a real local Ollama adapter first. Select a compact, appropriately licensed model only after checking memory and current documentation. Start with one inference at a time and a bounded context, then measure quality and memory pressure.
- **Connector:** a provider-neutral interface, fully working stateful evaluation adapter and real import adapter. Keep future Skool connectivity disabled. Every method must expose source/mode, coverage and supported operations; unsupported methods must fail explicitly.
- **Deployment:** loopback-only local operation initially. Serve the built frontend and API on the same origin for normal use where practical.

Separate connectors, persistence, analytics, retrieval, model calls, workflows and UI. Keep future paid AI providers, a server database and hosted deployment possible through documented interfaces and migration plans. Do not claim those upgrades are already implemented or zero-effort.

Avoid mandatory Docker, Kubernetes, Redis, a separate vector database, multiple AI agents or several large models on this 8 GB machine. Prefer native processes. Use bounded queues, incremental sync, pagination, caching and log rotation. Store transcripts and references instead of downloading the whole video library.

Check existing models and disk usage before downloading anything large. Keep the database on the internal disk by default; use the external SSD for optional archives/backups or model files only after verifying its path and filesystem. Handle its absence gracefully. Do not require the SSD for application startup unless I explicitly configure that dependency.

The application must start and offer data management, dashboards, search and deterministic reports when the model is unavailable. AI-dependent functions must show a genuine unavailable state, not canned answers disguised as AI.

## 5. Implement the actual product

Build these screens with working persistence, filters, loading/error/empty states and meaningful navigation. Wire every enabled control to a real implemented operation. Disable unavailable capabilities with an explanation.

For this phase, implement every core feature against the local community and its test records. Do not defer the application feature simply because real Skool access is deferred. References below to accessible data or supported publishing mean the selected adapter's capabilities; local publication changes only the simulated community. Any genuine live integration remains separately unverified.

### Overview and member management

- Community overview: available member totals, participation trends, unanswered questions, pending actions and connection health.
- Searchable member directory with group-specific identity, role, join date, membership information where available, tags, internal notes, last observed activity and data freshness.
- Member detail pages with evidence-linked activity history, progress where accessible, open support items and follow-up history.
- Saved segments such as new members, no observed contributions in a chosen period, pending onboarding and members needing staff attention. Use transparent rules with editable thresholds, not uncalibrated claims about who will cancel.

### Discussions and support

- Ingest accessible posts, comments, replies and reactions, including pagination and nested threads where supported.
- Identify questions that appear unanswered; keep AI classifications distinguishable from manually verified resolution states.
- Search, filter, assign, draft, review and resolve support items. Show a working internal thread link for synthetic records; use real source links only for genuine imported/connected records.
- Draft replies using approved knowledge and the current thread; permit edited approval and supported publishing.
- Surface repeated questions and useful topic summaries. Include evidence and coverage limits.

### Learning and events

- Course/module directory and member completion records from the local simulation now, or a verified source/explicit import later, with provenance displayed.
- Distinguish marked-complete lessons from proven viewing time or understanding. Track assignments, submissions and reviewer feedback separately.
- Show observed progress changes, stalled progress under configurable rules, and suggested next lessons within the member's access tier.
- Calendar, reminders and attendance import/sync for supported sources. Distinguish registration, attendance and attendance duration.
- Test configurable general/annual and other segments using labeled synthetic access rules. Ask for actual Social Eagle entitlement rules only when configuring the real community later; never present the fictional rules as real policy.

### Engagement and reporting

- Group-specific posts, comments, reactions, distinct contributors and active contribution days where observable.
- Leaderboard points/levels and changes from synthetic records now, with real native values only after later verification. Any custom contribution score is separate, documented and never presented as Skool's official score.
- Daily/weekly summaries, date comparisons, unanswered-question aging and response-time reports using an explicit definition of response/resolution.
- Downloadable CSV reports and readable summaries with scope, date range, sources, last sync and missing-data notes. Prevent CSV formula injection.
- Keep membership/billing reporting read-only where supported; do not pretend to access payments unavailable to the current role.

### Owner chat and automation controls

- A conversational interface to ask about members, participation, unresolved questions, available progress, course information and the bot's own actions.
- Structured, permission-checked tools for queries and supported actions. The AI must not execute arbitrary shell commands, unrestricted SQL or code supplied in community content.
- An automation screen with configurable triggers, conditions, schedules, quiet hours, limits and allowed actions.
- Jobs, review queue, action history, notifications, backups and a global pause switch. Show whether a queued item has merely been drafted, approved, sent or verified.

Use a clean off-white, charcoal and restrained crimson visual direction, readable tables, accessible contrast and a responsive layout. Keep technical debugging details in diagnostics, not in ordinary member-management flows. Include English support and evaluate Tamil/Tanglish handling if those occur in the actual approved material; do not promise untested language quality.

## 6. Data integrity and honest metrics

Use stable upstream IDs and group-scoped relationships, never display names as unique identities. Save source timestamps, observation timestamps, provenance and coverage. Preserve historical snapshots where needed for comparisons; do not fabricate history before collection began.

Synthetic history is permitted and required for evaluation, provided its origin is explicit and its identifiers are namespaced. Generate it reproducibly and never relabel it as observed real history. In live mode later, the rule against fabricating historical observations applies fully.

Define each metric in code and documentation. Use validated parameterized queries for counts and calculations; use AI to interpret the results.

Critical distinctions:

- No comments does not mean no visits, no learning or no value received.
- A last-seen timestamp does not measure session duration or minutes studied.
- A global Skool profile activity signal is not necessarily activity in our community.
- Likes/leaderboard points do not establish learning mastery or helpfulness.
- Lesson completion is not proof of watching the full video.
- Missing observations are not zero activity. Partial sync is not complete coverage.
- Bot/staff activity must be separable from member activity in reports.

Show unknown values as unknown, and incomplete periods as incomplete. Report observed contribution days if exact time online is unavailable. Never manufacture exact minutes. Do not estimate inactivity from data with known gaps without making those gaps explicit.

If testing a time-spent feature, use explicitly synthetic start/stop session events with documented idle/overlap rules, and also test the unavailable-data case. This validates the application's calculation without claiming Skool will provide those events or that elapsed time proves attention.

Apply UTC/Asia-Kolkata boundaries consistently. Handle rejoining members, deleted records, edited comments, pagination, retries and duplicated imports without silently corrupting totals. Enforce each member's course permissions in any member-facing reply.

## 7. AI answers with evidence

Implement knowledge ingestion for approved Markdown, text, text-based PDFs and supplied transcripts. Preserve file/lesson identity, versions and permission metadata. Detect scanned PDFs and explain OCR requirements instead of pretending their text was extracted.

Retrieve bounded relevant passages before generating answers. Prefer verified structured queries for member analytics. In evaluation mode, cite the actual stored synthetic lessons and records through working local links. Later, cite the actual authorized live/imported sources. Do not create fabricated external links. Abstain or ask a precise clarification when evidence is insufficient, contradictory or stale.

Treat posts, comments, imported documents and retrieved text as untrusted content. Instructions inside them cannot override application policy, access secrets, invoke admin tools or expand permissions. Do not accept a member's claim that they are an administrator as authorization.

Distinguish observed facts, calculated metrics and AI suggestions. Never use a model's self-reported confidence as the sole permission to publish. Keep source versions, retrieved evidence, policy version, model version and final action outcome for diagnosis, while minimizing retained personal content.

Provide structured-output validation, timeouts, bounded retries, cancellation and a circuit breaker. If the local model is too weak or slow, benchmark and report that honestly. Keep it in draft-only mode for the affected task. Do not silently enable a paid provider or send private member/course data to a free cloud service whose terms do not permit that use.

## 8. Controlled autonomy and durable execution

Use these defaults, with operator-configurable policies:

In evaluation mode, all these operations target only the local simulator. Include a clearly labeled evaluation policy that allows routine simulated replies so I can observe real AI-driven automation before approval. Consequential-action workflows can be tested entirely locally. No simulation setting or approval may authorize an external Skool action.

1. **Read/report automatically:** permitted data sync, calculations, search, summaries and internal task preparation.
2. **Draft initially:** replies, reminders, onboarding and suggested moderation actions.
3. **Automatic permitted actions after configuration:** specific proven FAQ replies or other allowlisted workflows, with targets, scope, limits and quiet hours set by the admin. Once a rule is authorized, do not require repetitive approval for each matching routine action.
4. **Explicit approval for consequential actions:** refunds, bans, deletion, billing changes, permission changes and bulk outbound messages.

Respect Skool's platform rules. Do not implement fake engagement, automated point farming or indiscriminate outreach. Clearly identify automated assistance rather than impersonating the mentor.

For writes, record a durable job, stable deduplication key, target, payload/version, approval and attempt history. Recheck permissions and relevant source state immediately before execution. Verify the remote outcome. A timeout after sending is an **unknown outcome**: reconcile it before retrying, or hold it for review. Do not claim exactly-once guarantees when the external system cannot provide them.

Prevent duplicate jobs across restarts and multiple launches using leases/locks and unique constraints. Include retry backoff, maximum attempts, failed-job review and graceful shutdown. After sleep, avoid a burst of outdated reminders; apply configurable catch-up or expiry rules.

The pause switch must stop new external actions and explain any already in progress. Show worker heartbeat, queue age and sync freshness. A broken connector or expired login must produce a visible alert.

## 9. Security, storage and recovery

- Bind locally by default, with authenticated admin access, protected sessions, safe first-run enrollment, appropriate CSRF/origin/host checks and no public default credentials.
- Enforce permissions in the backend. Validate uploads, paths and payloads; prevent XSS, SQL injection, path traversal and unsafe URL fetching.
- Store secrets using an appropriate local secret store or protected environment configuration; redact logs. Keep secrets, private data, browser profiles and raw member exports out of Git.
- Implement usable retention, export and deletion controls. Minimize stored personal data and document how any enabled model provider processes it.
- Take consistent SQLite backups using supported backup methods; do not blindly copy a live database file while writes are in progress. Back up required app metadata and knowledge records, protect access, and test restore into a separate location.
- Keep remote access and public hosting disabled initially. Document the authentication, TLS, secrets, deployment and operational work needed before enabling them.

## 10. Build in verified milestones

Implement small end-to-end slices, each including persistence, API, UI and checks:

1. Environment inspection, plan, application shell, evaluation-mode isolation and persistent local simulator.
2. Reproducible scenario data, member directory, import validation and deterministic reporting.
3. Discussion inbox, knowledge search, actual local model integration and evidence-linked chat/replies.
4. Progress, leaderboard, event and membership views driven by simulated events, with coverage and provenance.
5. Durable workflows, reviewed and automatic local actions, reconciliation, pause and recovery.
6. Full UI integration, authentication, backup/restore, regression checks, measured performance and a repeatable approval walkthrough.

The independent application is complete when its applicable acceptance checks pass and the workflows can be demonstrated without Skool access. Report **Independent application verified; live Skool connection deferred until approval**. Do not mark deferred connectivity as a failure of this phase, or present local results as proof of live integration.

## 11. Acceptance tests and verification

Create meaningful tests for actual risks, with separate unit, local integration, AI and UI checks. No live Skool checks are allowed or required in this phase. Document future live checks separately; excluded live checks must not count as passed or make the independent test suite fail.

Required evidence:

- Reproducible dependency installation, migration, startup, frontend build, type checks, lint and core automated tests.
- Known-fixture analytics exactly match expected results, including time boundaries, missing data, duplicate records and group isolation.
- Seeded/imported samples reconcile with their known source records; simulated connection failures and expired-session responses do not masquerade as an empty community.
- Member search, filters, notes, supported progress, support queues, reports, chat, pause and settings work through the UI.
- A representative AI evaluation set includes answerable, unanswerable, conflicting-source, restricted-course, analytics and prompt-injection cases. Supply synthetic lesson material and at least 30 meaningful cases, so no actual course material is needed. Use held-out paraphrases rather than training the answers into canned responses. Report sample size, failures and limitations; this is not a production accuracy guarantee.
- Unauthorized actions, cross-member/course disclosure, invented metrics and duplicate external actions fail the release gate.
- Test restart, double-launch, timeout-after-send, partial sync, model outage, low disk space, missing SSD and sleep/wake recovery as applicable. Use controlled fault injection where necessary and label it.
- Demonstrate a consistent backup and restore into a separate evaluation database without altering the running data.
- Measure response time, memory pressure, queue behavior and representative workload on this machine. Do not promise a member capacity or response-time target without measurements.
- Prove that evaluation mode cannot initialize a live Skool connector, contact Skool through application jobs or send external messages, even if credentials are present. Validate this with controlled test doubles/network spies, not by contacting Skool.
- Demonstrate: add a new synthetic question, generate a source-grounded answer, publish it in the local thread, restart the worker and confirm no duplicate. Then change a member's progress and confirm the report changes. Save the expected-versus-actual results for my review.

Run checks, diagnose failures, fix the underlying causes and rerun affected checks. Do not remove assertions, disable protections or swallow exceptions merely to make tests pass. Missing Skool access must never block these checks. If a local dependency or AI-quality issue remains, document that actual issue and continue independent work.

## 12. Deliverables and easy operation

Provide the actual implementation and:

- `README.md`: purpose, features, limitations, setup and daily use.
- `CLAUDE.md`: concise persistent engineering instructions and commands.
- `docs/BUILD_SPEC.md`, `docs/STATUS.md`, `docs/CAPABILITIES.md` and an acceptance matrix.
- Architecture/data model, permissions/data-handling notes, backup/restore guide, troubleshooting and upgrade plan.
- `.env.example` with placeholders only, lockfiles, migrations and a careful `.gitignore`.
- Working scripts for `setup`, `start`, `stop`, `doctor`, `check`, `backup` and `restore`; shell scripts must handle paths with spaces, Apple Silicon, port conflicts and repeated execution safely.
- A repeatable `seed-evaluation`/`reset-evaluation` command with a fixed seed, isolation checks and an explicit warning before discarding evaluation changes; it must never target a live database.
- A normal start command that starts both the application and worker, reports their health and prints the actual local URL. Stop scripts must stop only this project's processes.
- A verification report with commands, exit results, dates and clearly separated local, fixture, model-evaluation and live results. Use sanitized screenshots with test data for UI evidence.
- A final feature matrix with separate independent verification and live integration columns. Keep future live connection marked **deferred until approval**.
- `docs/APPROVAL_WALKTHROUGH.md` with example owner questions, event-injection steps, expected data changes, real AI response examples, measured results and limits of the local evaluation.

After a working implementation is ready, run it and open the local UI if the environment permits. Demonstrate the principal flows. Explain how I can start, stop, back up and resume development. Do not publish a repository, expose the service publicly, buy anything or send real community messages without appropriate authorization.

Present the complete independent application for my review. Do not immediately require Skool login or automatically proceed to connection. The decision to approve and connect belongs to me after I inspect the results.

If context or subscription limits interrupt development, save a precise checkpoint in `docs/STATUS.md`, including the next command and remaining verification. Resume from that checkpoint on the next session. Do not represent paused work as completed.

## 13. Later phase — only after my explicit approval to connect

This section is a future integration plan, not an instruction to start connecting now. Keep the same application and implement the real adapter only after I explicitly approve the results and authorize connection. No rebuild or artificial separation into a throwaway product is intended.

At that point, ask for the community URL, actual role, group plan and permitted connection method. Enter secrets only through secure local setup or the provider's login, never chat. Check current documented supported interfaces and record actual capability evidence. Do not invent endpoints, webhook events or scopes, and do not promise every simulator feature is exposed by Skool.

If a necessary operation lacks a supported interface, assess browser automation only within authorized access and platform restrictions. Do not bypass CAPTCHA, access controls, paywalls or rate limits. Any permitted browser connector needs a dedicated protected profile, conservative rates, stable locators and session-expiry handling.

Use a separate live database/namespace. Do not carry over synthetic identities, queued jobs, simulated approvals or simulated outbound messages. Keep outward actions disabled initially; reconfigure live targets and rules explicitly. Validate a small read, reconcile real records with their source, and then test one specifically authorized write and verify its outcome. Report source-specific unavailable fields honestly, including exact time spent if absent.

Record live verification separately from prior application acceptance. Approval to connect enables integration work; it does not certify that all planned integrations work or grant unrestricted actions.

## Official references to verify during implementation

- Claude Code setup: https://code.claude.com/docs/en/setup
- Claude Code verification practices: https://code.claude.com/docs/en/best-practices
- Skool integration: https://help.skool.com/article/56-zapier-integration
- Skool platform policy: https://help.skool.com/article/179-platform-policy
- Skool analytics definitions: https://help.skool.com/article/216-analytics-definitions
- Skool points/levels: https://help.skool.com/article/31-how-do-points-and-levels-work
- Ollama macOS support: https://docs.ollama.com/macos
- Ollama memory/context considerations: https://docs.ollama.com/context-length
- Ollama local-only mode: https://docs.ollama.com/faq
- FastAPI: https://fastapi.tiangolo.com/
- SQLite deployment suitability: https://www.sqlite.org/whentouse.html

Begin now by inspecting the workspace and environment, creating the milestone plan and durable project instructions, and implementing the independent application with a real local simulator. Build, run, test and demonstrate it without asking for Skool access. Keep live connection deferred until I approve the application and explicitly authorize that next phase.
