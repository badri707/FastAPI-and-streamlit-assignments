# Skool workflow reference

Status of documentation checks: **not re-verified in this session.** help.skool.com was unreachable from the build sandbox on 2026-10-20. The "Documented" column repeats what the build spec states its author reviewed on 2026-10-20. Re-check each article on the Mac and update this table.

| Workflow | Documented (per spec) | Observed publicly | Implemented locally | Unverified |
|---|---|---|---|---|
| Points & levels ([31](https://help.skool.com/article/31-how-do-points-and-levels-work)) | Likes **received** on posts/comments/replies award points to the author | — | Likes given vs received kept separate; points only from observed leaderboard snapshots | Level thresholds; whether rules changed |
| Daily activity ([103](https://help.skool.com/article/103-what-is-daily-activity)) | Includes engagement events; documented in UTC | — | Active days computed on IST and labelled as such; UTC bounds stored on every report | Exact event list |
| Course permissions / tiers ([23](https://help.skool.com/article/23-how-to-set-permissions-for-a-course)) | Courses can be restricted by tier/level | — | Entitlements modelled separately from plan labels | How tiers map to Social Eagle labels |
| Manual course access ([144](https://help.skool.com/article/144-how-to-grant-course-access-to-members)) | Admins can grant course access | — | Entitlement history with valid_from/to | — |
| Classroom & transcripts ([166](https://help.skool.com/article/166-what-is-classroom)) | Classroom holds courses; transcripts available | — | Lesson body/transcript excerpts for permission-scoped search (synthetic) | Export method for transcripts |
| Zapier ([56](https://help.skool.com/article/56-zapier-integration)) | Membership triggers, invitations, course unlocks; Pro plan | — | Not integrated | Field list; plan requirement for Social Eagle |
| Plugins / invitation webhook ([176](https://help.skool.com/article/176-how-to-use-plugins)) | Invitation webhook | — | Not integrated | Payload; whether other events exist |
| Platform policy ([179](https://help.skool.com/article/179-platform-policy)) | — (to read) | — | No automated engagement, no writes | Policy on automated reads |
| Analytics definitions ([216](https://help.skool.com/article/216-analytics-definitions)) | — (to read) | — | — | Definitions |
