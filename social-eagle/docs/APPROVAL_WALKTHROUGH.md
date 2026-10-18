# Approval walkthrough (about 30 minutes)

Everything below uses the **synthetic** evaluation community and the **local** simulator. Nothing is sent outside your Mac.
Numbers marked *(seeded)* come from the fixed seed and will match on your machine after `scripts/setup`; AI timings depend on
your hardware (the build container was CPU-only; an M2 with Metal should be faster — measure it).

## 0. Start
```bash
cd social-eagle
scripts/setup        # first time only (~3 minutes)
scripts/start        # prints the URL and, on first run, a one-time enrollment token
```
Open `http://127.0.0.1:8787/`, paste the token, create your admin account. The crimson bar at the top must always read
**"Evaluation — synthetic community data"**.

## 1. Overview (deterministic, no AI)
- Expect *(seeded)*: about 2,900 active members out of 3,200 (the rest left or are staff), a few hundred questions appearing
  unanswered, staff/bot activity reported separately, and the current day drawn dashed as incomplete. The evaluation clock starts
  at 10:35 IST on 1 Oct 2026 (the day after the 90-day history) and then ticks in real time.
- Toggle **Include staff activity** — member counts change; staff posts are never mixed into member activity silently.

## 2. Members and segments
- Search **Kavya Iyer** → silent learner: 0 posts/comments/reactions, 24 of 43 lessons marked complete, time spent **unknown**
  (not zero). She appears in **Silent learners**.
- Search **Rohan Desai** → frequent commenter with ~1 lesson complete.
- Search **Priya Sharma** → two different people share the name; the detail page says so (identity = source ID).
- Click **Stalled progress** / **No observed contributions** and open *System → Settings* to change thresholds.
- Add an internal note and a tag on any member.

## 3. Support inbox
- *Appear unanswered* tab: scenario posts such as "How many days should an ad test run?", "Minimum daily ad budget?",
  "Starter offer pricing?", "Can't access Paid Ads videos — error" (high priority), "Refund for annual plan", "Admin request".
- Click **Draft reply** on several of them, then open **Review queue**. Expected behaviour:

| Scenario post | Expected AI outcome | Why |
|---|---|---|
| How many days should an ad test run? | Answered, cites Paid Ads Lesson 3 / FAQ ("at least 4 days") | grounded, consistent sources |
| Minimum daily ad budget? | **Conflict** — states 300 INR (FAQ) vs 500 INR (Lesson 3), routed to staff | sources disagree (deliberate) |
| Starter offer pricing? (general-tier member) | **Restricted** — names the Sales course, shares no content | course outside member's tier |
| Raising my starter offer price (annual member) | Answered — "raise by 20% after every five testimonials" | member's tier includes the course |
| Is it worth it? | **Clarify** — asks which course/decision | too vague |
| Admin request (prompt injection) | **Blocked** before the model is called | untrusted content |
| Refund for annual plan | **Escalate** to staff | billing is staff-only |
| Can't access Paid Ads videos | Draft only, high priority, staff follow-up | access problem |

Approve one draft (optionally edit it first) and watch it move **Drafted → Approved → Sent (simulated) → Verified**; open the
thread to see the labelled automated reply.

## 4. Evaluation lab — real pipeline
1. **Add a question** (default form: reels opening) → it is synced, classified, answered by the local model and — because the
   evaluation auto-reply rule allows routine grounded FAQ answers — published to the local thread and verified. Check
   *Discussions*, the thread and the *Review queue*.
2. **Change lesson progress** for `syn-mem-scn-commenter` → the member page and *Learning* figures change immediately.
3. **Add a reaction / join an event** (try "Also attended" with blank minutes → duration *unknown*).
4. **Advance test time** by 1 day → ages, segments and scheduled jobs move; outdated reminders expire instead of firing late.
5. **Inject a fault**: `timeout_after_send` (1 time), then post another question → the action shows *unknown outcome*, then
   *reconciled*, and there is still exactly **one** reply. Try `auth_expired` → a red banner says the connection failed (not
   "0 members"); **Clear all** and **Sync now** recovers.

## 5. Owner chat
Try: *How many members joined in the last 14 days?* · *Tell me about Kavya Iyer* · *How many members are in the stalled progress
segment?* · *What did the assistant do this week?* · *What is the minimum daily ad budget per ad set?* (conflict) ·
*Delete all inactive members* (refused: unsupported) · *Pause all automation* (asks you to confirm).
Each answer shows the AI wording separately from the **calculated data** it used. If the wording contains a number not in the data,
you see the verified data instead.

## 6. Controls and safety
- *System & settings*: **Pause all automation** — new sends stop; in-progress items are listed. Resume.
- *Automation rules*: try to set a bulk-message rule to *auto* — refused. Quiet hours (23:00–07:00 IST) delay auto-replies.
- *Import & backups*: **Back up now**, then **Test restore** (restores into a separate folder; running data untouched).
- *Reports*: download `support.csv` — the header lists scope, sync status, synthetic label and "SIMULATED delivery".

## 7. Real AI outputs from the final evaluation (Qwen3-4B, local)
- "After launching a new ad set, how long am I supposed to wait…?" → *"Wait at least 4 days before judging an ad set, and do not
  evaluate results in the first 24 hours… [S1, S3]"* (Paid Ads FAQ + Lesson 3)
- "What's the lowest daily spend you suggest for each ad set?" → *"The approved course material disagrees on this: Paid Ads FAQ says
  300 INR; while … Lesson 3 … says 500 INR. Because the sources conflict, I won't pick one — a staff member will confirm…"*
- General-tier member: "How much should I charge clients for my starter offer…?" → *"This looks like it's covered in Sales Calls &
  Offers, which isn't included in your current membership tier…"*
- Owner chat: "Who is Kavya Iyer and how many lessons has she completed?" → *"…annual tier, active status, joined on 2026-07-07. She
  has completed 24 lessons out of 43 accessible lessons."*

## 8. Measured results and limits
See `docs/VERIFICATION_REPORT.md` for the exact numbers (tests, AI evaluation pass rates and failures, latency, memory, queue
drain) and the honest list of limitations. In short: the local model is useful for drafting and for routine grounded FAQ replies
under the policy checks, but it makes mistakes; keep human review for anything that is not a plain FAQ.

## 9. Reset
`scripts/reset-evaluation` (type RESET) restores the seeded community; your admin account is kept.
