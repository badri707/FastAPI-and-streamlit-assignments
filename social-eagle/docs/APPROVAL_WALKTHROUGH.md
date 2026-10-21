# Mentor walkthrough (about 15 minutes)

**Boundary first:** everything shown in the test workspace is **synthetic, fictional data**. It proves the application's logic, not production accuracy. The public Skool connector has **not yet read a live page** because the build sandbox blocked skool.com. No private Skool access has been requested or used. Nothing is ever posted to Skool.

## 0. Start
```bash
cd social-eagle && scripts/setup.sh && scripts/seed-evaluation.sh --yes && scripts/start.sh
```
Open http://127.0.0.1:8765, sign in with the token from `data/admin_token`, then click **test** in "Switch workspace".

## 1. Input evidence
- `app/fixtures.py` lists every synthetic record: who posted what and when, each progress snapshot, every staff response.
- **Data health** (date 2026-10-19): the membership, discussions and progress sources are all `ok`. Sync runs show method `fixture` and their coverage windows.

## 2. Calculations you can check by hand (2026-10-19 IST)
| Metric | Expected from raw records | Shown |
|---|---|---|
| Learner posts | 8 (Rahul ×4 incl. 23:50 IST; Isha, Sana, Karthik, Priya). Rahul's 00:10 IST post on the 20th is excluded, even though its UTC date is the 19th | Overview / Participation |
| Learner comments | 4 before the late delta, 5 after (revision 2) | Reports r1 vs r2 |
| Likes given / received | 6 / 6 (r1); 5 / 6 after the removed like (r2) | Participation |
| Unresolved questions | 4 (Dev 38 h, breach; Isha with peer + bot ack only; Rahul reopened; Sana awaiting member) | Support |
| Awaiting review | Karthik's Assignment 1 | Assignments |
| Unknown progress | Nila (no data) and Tara (new, no data); Isha's change is "not comparable" because the denominator changed | Learning |

Each number is also asserted in `tests/test_scenarios.py` against an independent calculator (`tests/expected.py`).

## 3. Generated report
**Reports** → 2026-10-19 r1 (scheduled) and r2 (revised after late data; the reason is shown). Download the CSV/JSON. Use the browser's Print on the HTML report.

## 4. Failure recovery
- 2026-10-20 r1 is **degraded**: discussions sync failed (simulated HTTP 503). Participation shows "UNAVAILABLE — values withheld, not zero".
- 2026-10-20 r2 is **complete** after recovery. Running it again returns the same report with no duplicate notification.
- 2026-10-21 r1 is **unavailable**: total simulated outage.

## 5. Member evidence report
Members → Rahul S. (`m-rahul`) → **Printable evidence report**. It shows his posts and his reopened question side by side with the coach's response and resolution evidence. Other learners are not named. Note that there are two different "Rahul S." members with different IDs.

## 6. Public mode
Click **public**: banner "only logged-out public reads". The overview shows the external reference community with a **failed** sync and the actual error (`ProxyError: 403`). It does not show zero members.

## 7. The bot in action (simulated community)
1. Test workspace → **Community**. Choose *Acting as: Dev* and post in **Questions**: "How do I install the Meta pixel before running conversion campaigns?" Then click **Run bot now** in the thread (the worker also does this within 30 s). EagleBot replies with a quote from the Facebook ads basics lesson and its source link. The state is **answered**, not closed.
2. Post "Can I get a refund for the annual plan?" The bot acknowledges the question and escalates it. Open **Bot & inbox** to see the reason, then answer as Coach Kavya from there.
3. Post "help?" The bot asks one clarifying question. Reply in the thread with details and the bot resumes.
4. Act as *Vikram (General)* and ask about the "high-ticket pricing playbook". The bot does not use VIP-only material and escalates instead. Ask the same as *Sana (VIP)* and she gets an answer.
5. Click **Member confirms solved**: the question closes with the member's confirmation as evidence. Today's numbers appear on Overview, Support and Participation, marked *in progress* until the day ends.

## What this does not prove
Accuracy on real Social Eagle data, AI-written answer quality (no local model run yet; answers shown are verbatim quotes), capacity at 10k members (not measured), 24/7 availability (local only).
