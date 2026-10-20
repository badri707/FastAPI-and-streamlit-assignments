# Field-by-field feasibility matrix

"Documented integration" refers to the Skool help articles listed in the spec. They were reviewed by the owner on 2026-10-20 but **could not be re-checked in this session** (help.skool.com was blocked by the build sandbox). Zapier/plugins are documented for membership triggers, invitations and course unlocks (Pro plan). This is not evidence of a general member/activity/progress API, and also not evidence that none exists.

| Required field | Likely source | Visibility | Documented integration | Current implementation | Test evidence | Remaining limitation |
|---|---|---|---|---|---|---|
| Community name, displayed member/online totals | Public group page | Public (if group is public) | none needed | Parser → `communities.displayed_*` as displayed strings | Mock fixture only | Live markup unverified; "1.4k" is approximate |
| Post title, excerpt, author id/name, created time, like/comment counts | Public feed | Public (feed excerpt) | none | Parser → `posts` (is_excerpt) + `members` | Mock fixture only | Unverified field names; first page(s) only; relative times kept as `unknown` precision |
| Full threads, comments, replies | Thread pages | Possibly public | none | Not parsed yet | — | Next milestone; must stay bounded |
| Who liked what, when | — | Generally not shown publicly | none known | Import only | Synthetic | Public mode cannot compute likes given |
| Member directory | Members tab | Typically requires login | Zapier membership triggers (Pro) | Import only | Synthetic | Requires private access later |
| Batch / cohort membership | Social Eagle internal | Private | none | Import (`cohort_memberships`) | Synthetic | Company must supply mapping |
| Plan label (General/Annual/VIP) | Skool billing / company records | Private | Zapier membership info (unverified fields) | Import (`access_periods`) | Synthetic | Not assumed to equal Skool tiers |
| Course access / unlocks | Skool Classroom permissions | Private | Zapier course-unlock (unverified fields) | Import (`entitlements`) | Synthetic | — |
| Lesson completion | Classroom progress | Private, per member | none known | Import (`progress_snapshots`) | Synthetic | Completion ≠ watch time |
| Lesson deadlines | Company schedule | Company | n/a | Configured import (`lesson_deadlines`) | Synthetic | Never guessed |
| Assignment submissions | Configured post category or manual label | Private community posts | none | Import (`submissions`) with classification | Synthetic | Category mapping must be configured |
| Feedback / review / result | Staff comments, internal records | Private | none | Import (`feedback`) | Synthetic | — |
| Questions & responses | Posts/comments | Private community | none | Import (`support_questions`, `support_events`) | Synthetic | AI/heuristic classification not built |
| Leaderboard points/rank | Leaderboard tab | Sometimes public snippet | none | Import (`leaderboard_snapshots`) | Synthetic | Partial snippets labelled |
| Time online / watch time | — | Not available | none | **Deliberately not computed** | — | Never inferred |

A Google API (Sheets/Gmail) can only be an optional destination. It cannot unlock private Skool data.
