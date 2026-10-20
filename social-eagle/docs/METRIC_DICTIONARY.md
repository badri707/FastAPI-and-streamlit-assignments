# Metric dictionary (calculation version `metrics-2026.10.20-1`)

Code: `app/analytics/metrics.py`. Every metric is computed with parameterised SQLAlchemy queries over an explicit interval `[start, end)` in UTC. The interval is derived from Asia/Kolkata calendar days.

**Cutoff and as-of.** Only records *observed* by the data cutoff (generation time) are used. Time-dependent states (ages, breaches, active enrolment or batch, entitlement) are evaluated **as of the end of the interval**. Re-running a past report with unchanged data therefore gives an identical result.

**Learners vs staff/bots.** Learner metrics include only `role = member`. Staff, admin and bot activity is reported separately.

| Metric | Definition | Not to be read as |
|---|---|---|
| posts / comments | Learner-authored posts/comments whose `created_at` falls in the interval, excluding items with a confirmed deletion observed by the cutoff (counted separately). | Visits, reading, or time online. |
| likes given | Reactions whose actor is a learner and whose `created_at` falls in the interval; removed likes (confirmed) excluded and counted separately. | Points. Giving likes does not earn Skool points. |
| likes received | Reactions in the interval whose target's author is a learner (regardless of who gave it). | Helpfulness or learning. Per Skool's documented rule (spec, not re-verified), points come from likes **received**. |
| distinct contributors | Learners with ≥1 post, comment or like given in the interval. | Active members (quiet learners exist). |
| active days (7/30) | Distinct Asia/Kolkata dates with ≥1 observed post, comment or like given, in the 7 or 30 days ending at interval end. Skool's own daily activity is documented in UTC; this app labels its IST basis. | Minutes or sessions online. |
| progress (recorded) | Latest progress snapshot observed by as-of: completed lessons / total lessons as known at that observation. | Proof of watching, comprehension or mastery. |
| progress change | Latest snapshot inside the interval minus the latest snapshot before the interval, **only** if both have the same lesson-set hash and denominator. Otherwise `not_comparable`, `no_baseline` or `no_observation_in_interval`. | — |
| progress unknown | Active, enrolled course with no snapshot. Never treated as zero. | Inactivity. |
| deadline status | For each lesson deadline of a cohort, for each member of that cohort *at the due time*: `overdue` only if the lesson is non-optional, released by the due date, the member was entitled at the due date, the member is past the grace period, and the latest snapshot observed **after** the due date lacks the lesson. Otherwise `completed_marker_recorded`, `in_grace_period`, `excluded_no_access`, `unknown_no_progress_data` or `unknown_stale_progress`. | — |
| batch status | `current` if any cohort membership is active at as-of, `alumni` if only past ones, else `no_batch_recorded`. Independent of plan label and course access. | Subscription status. |
| plan labels | Active access periods (General/Annual/VIP business labels) at as-of; `unknown` if none. | A Skool billing product or course access. |
| assignments submitted / feedback delivered / awaiting review / reviewed-not-delivered | Separate facts from submission and feedback records; `ambiguous` classifications are listed for manual review, never counted. | Assessment result (a separate field). |
| first staff response time | Hours (calendar or Mon–Sat 10:00–19:00 IST working hours, configurable) from question to first `staff_response`. Peer, bot and clarification responses are measured separately. | Resolution. |
| question state (evidence) | `resolved` if `resolution_confirmed`/`closed` after the last `reopened`; else `awaiting_member` if the latest clarification request has no later member reply; else `awaiting_staff`. | — |
| response-target breach | No staff response and elapsed > target at as-of, or first staff response later than the target. Demonstration target 24 h. | A company commitment. |
| outreach candidate | Any of: overdue eligible lesson; question awaiting staff past target; current-batch member, past grace, with no observed contribution **and** no comparable progress increase in 14 days — evaluated **only** when discussion coverage is complete for that whole window. Each reason is listed. | A risk, blame or churn score. Low points never trigger outreach. |
| leaderboard change | Point/rank differences between two snapshots of the same period; labelled `partial_snapshots_members_in_both_only` unless both are complete. | The official full leaderboard. |
