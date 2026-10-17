# Metric definitions

All metrics are computed in `backend/app/services/metrics.py` with parameterized SQL. The API exposes the same text at
`GET /api/metrics/definitions`. AI may interpret these numbers but never computes them.

| Metric | Definition |
|---|---|
| Date range | Asia/Kolkata calendar days, inclusive at both ends, converted to a half-open UTC range. |
| Contribution | A post, comment or reply authored, or a reaction given, in the group, not deleted. |
| Member activity scope | Excludes staff and the automated assistant unless `include_staff` / `include_bot` is set. Staff and bot posts/comments are always reported separately. |
| Distinct contributors | Members with ≥1 contribution in the range. |
| Active contribution day | A distinct (member, IST date) with ≥1 contribution. **Not** time online. |
| Active members | Members with status `active` at the source, excluding staff and bots. |
| Appears unanswered | Support item in open/assigned/drafted with no reply from anyone other than the asker. An observed fact, not a resolution. |
| First response time | First reply by someone other than the asker minus question time; also split by responder (member/staff/bot). Median and p90. |
| Resolution time | Human-marked resolution minus question time. Only human-verified resolutions count. |
| Lesson completion | "Marked complete" at the source. Does **not** prove the video was watched or understood. |
| Course finish | Eligible active member (tier has access) with every lesson of the course marked complete. |
| Stalled progress | Has marked-complete lessons, none in the last N days (default 14), accessible lessons remaining. |
| No observed contributions | Active, joined before the window, no contributions in N days (default 21). They may still be reading or learning. |
| Attendance | Registration, attendance and duration are separate. Missing leave time ⇒ duration **unknown** (never 0). Walk-ins counted separately. |
| Leaderboard | SYNTHETIC points modelled on the public description (likes received → points; levels by threshold). Not Skool's official score; does not measure learning or helpfulness. |
| Time spent | Only from explicitly SYNTHETIC session start/stop events. Concurrent sessions allowed; a stop closes the earliest open start; a start without stop within 30 min is capped at 30 min; overlaps merged. No events ⇒ `unavailable` (unknown), never 0. |
| Coverage notes | Reports flag today as incomplete, days before the first observation as unknown, non-OK sync status, and synthetic data. |

Known-answer fixtures for these definitions: `backend/tests/test_metrics_fixture.py`.
