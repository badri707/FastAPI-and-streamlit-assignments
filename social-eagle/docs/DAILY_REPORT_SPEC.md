# Daily report specification

## Schedule and policy
- Default: **09:00 Asia/Kolkata** for the previous local calendar day (`SE_REPORT_HOUR`, `SE_REPORT_MINUTE`). This is a proposed default, not company policy.
- The worker records the last planned date in `app_state`. The first start does not backfill; scheduling begins with the next due date. Use **Run now** for past dates or ranges (up to 62 days).
- **Woken late** (more than 60 minutes after the due time): the missed run is recorded as a `missed_run` event and the report is generated with trigger `catchup`.
- **More than 7 days late** (`SE_CATCHUP_MAX_DAYS`): recorded as `expired_run` and not generated automatically. This avoids a burst of stale reports after a long sleep.
- Job dedupe key `daily_report:<community>:<date>` (UNIQUE) means two workers or a restart cannot create duplicate reports.
- Local operation only: nothing runs while the Mac sleeps or is off. The dashboard shows the worker heartbeat.

## Status
- `complete`: every configured source (membership, discussions, progress) has a successful run whose coverage includes the whole interval.
- `degraded`: some sources cover the interval and some don't. Sections depending on a missing source are marked **unavailable** with the reason, and no numbers are shown.
- `unavailable`: no configured source covers the interval. The report says so; it never shows zero activity.

## Revisions
The report content hash covers the interval, sections, availability, settings, calculation version and per-source health states. It excludes the cutoff timestamp.
- Same hash as the latest revision: the existing report is returned. No new file and no new notification.
- Different hash: a new revision is created with `supersedes_id` and a generated `revision_reason`, e.g. "participation data changed". Earlier revisions are never modified, and the HTML view of an old revision links to its successor.

## Contents
Interval (IST dates plus UTC bounds), timezone, generation time, cutoff, source modes, data health, member coverage and breakdowns, participation (interval plus 7/30-day), recorded learning progress and deadline checks, assignments, wins, support (new, unresolved, response times, breaches, awaiting staff or member), outreach candidates with reasons, staff follow-ups with owner, leaderboard observations, limitations, calculation version and source references.

## Outputs
`data/reports/<community>/<first>_<last>/r<revision>/` holds `report.html` (printable), `report.json`, `summary.csv` and `follow_ups.csv`. CSV cells starting with `= + - @ tab CR` are prefixed with `'`.

## Delivery
Generating a report adds an **in-app** outbox row (`pending → sent`). Email and Google Sheets are not implemented; any non-in-app channel is set to `blocked`. Rows in the `unknown` state are never retried automatically. The global pause holds delivery.
