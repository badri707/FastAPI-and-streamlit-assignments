"""SYNTHETIC Social Eagle test workspace — fictional people, courses and records.

Nothing here is real Social Eagle data or real Skool data. The plan labels,
access rules, deadlines and response targets are invented to exercise the
workflows in spec section 1A and must never be presented as company policy.

The fixture is a deterministic timeline of import bundles. ``steps()`` returns
(ingest_time_utc, bundle) pairs; each bundle goes through the normal validated
importer, exactly like a real import would.

Reporting day used by the scenarios: 2026-10-19 (Asia/Kolkata).
"""
from __future__ import annotations

import copy
from datetime import datetime
from zoneinfo import ZoneInfo

from app.timeutil import parse_ts

IST = ZoneInfo("Asia/Kolkata")
SLUG = "social-eagle-synthetic"
SOURCES = ["membership", "discussions", "progress"]
REF = "fixture://social-eagle-synthetic"


def ist(s: str) -> str:
    """'2026-10-19 10:15' (Asia/Kolkata) → ISO string with offset."""
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=IST).isoformat()


def at(s: str) -> datetime:
    ts = parse_ts(ist(s))
    assert ts is not None
    return ts


COMMUNITY = {"slug": SLUG, "name": "Social Eagle — SYNTHETIC TEST WORKSPACE", "is_synthetic": True,
             "is_company_community": True, "expected_sources": SOURCES}


def _base(source: str, observed: str, cov_start: str, cov_end: str, **kw) -> dict:
    return {"format": "social-eagle-import/1", "community": COMMUNITY, "source_name": source,
            "source_ref": f"{REF}/{source}/{observed.replace(' ', 'T')}", "method": "fixture",
            "observed_at": ist(observed), "parser_version": "fixture-1",
            "coverage": {"start": ist(cov_start), "end": ist(cov_end), "status": "complete"}, **kw}


def _member(id_: str, name: str, role: str = "member", joined: str | None = "2026-09-01 10:00") -> dict:
    return {"id": id_, "name": name, "role": role, "joined_at": ist(joined) if joined else None}


DM_LESSONS = [
    {"id": "dm-l1", "title": "Marketing fundamentals", "position": 1,
     "body": "Marketing starts with a clear customer persona and an offer that solves a specific problem."},
    {"id": "dm-l2", "title": "Customer personas", "position": 2,
     "body": "A customer persona describes demographics, goals, objections and where the customer spends time online."},
    {"id": "dm-l3", "title": "Facebook ads basics", "position": 3,
     "body": "Install the Meta pixel on every page before running conversion campaigns; start with a small daily budget."},
    {"id": "dm-l4", "title": "Landing pages", "position": 4,
     "body": "A landing page should have one call to action and match the promise of the ad."},
    {"id": "dm-l5", "title": "Bonus: copywriting swipe file", "position": 5, "optional": True,
     "body": "Optional examples of headlines."},
    {"id": "dm-l6", "title": "Retargeting (drip release)", "position": 6, "released_at": ist("2026-11-01 00:00"),
     "body": "Retargeting shows ads to people who already visited."},
]
ENT_LESSONS = [
    {"id": "ent-l1", "title": "Validating an idea", "position": 1, "body": "Validate demand by pre-selling before building."},
    {"id": "ent-l2", "title": "Pricing your first offer", "position": 2, "body": "Price on value delivered, not on hours spent."},
    {"id": "ent-l3", "title": "First ten customers", "position": 3, "body": "Reach out personally to your first ten customers."},
    {"id": "ent-l4", "title": "Systems", "position": 4, "body": "Document repeatable tasks before hiring."},
]
VIP_LESSONS = [
    {"id": "vip-l1", "title": "VIP: high-ticket offer design", "position": 1,
     "body": "VIP-ONLY MATERIAL: the high-ticket pricing playbook uses a three-tier anchor offer."},
    {"id": "vip-l2", "title": "VIP: partnerships", "position": 2, "body": "VIP-ONLY MATERIAL: joint venture structures."},
    {"id": "vip-l3", "title": "VIP: scaling ads", "position": 3, "body": "VIP-ONLY MATERIAL: scaling budgets by 20% per day."},
]

LEARNERS = ["m-anika", "m-rahul", "m-rahul2", "m-meera", "m-vikram", "m-sana", "m-priya", "m-dev", "m-isha",
            "m-karthik", "m-nila", "m-new"]


def membership_bundle(observed: str = "2026-10-20 02:00", vikram_name: str = "Vikram") -> dict:
    p = lambda m, f="2026-09-01 10:00", t=None: {"member": m, "from": ist(f), "to": ist(t) if t else None}  # noqa: E731
    return _base("membership", observed, "2026-06-01 00:00", observed,
                 members=[
                     _member("s-coach", "Coach Kavya", "staff", "2026-01-01 10:00"),
                     _member("s-mentor", "Mentor Arjun", "staff", "2026-01-01 10:00"),
                     _member("b-eaglebot", "EagleBot", "bot", "2026-01-01 10:00"),
                     _member("m-anika", "Anika"),
                     _member("m-rahul", "Rahul S."),
                     _member("m-rahul2", "Rahul S.", joined="2026-09-15 10:00"),  # duplicate display name, different person
                     _member("m-meera", "Meera", joined="2026-06-01 10:00"),
                     _member("m-vikram", vikram_name),
                     _member("m-sana", "Sana"),
                     _member("m-priya", "Priya"),
                     _member("m-dev", "Dev"),
                     _member("m-isha", "Isha"),
                     _member("m-karthik", "Karthik"),
                     _member("m-nila", "Nila"),
                     _member("m-new", "Newcomer Tara", joined="2026-10-16 10:00"),
                 ],
                 courses=[
                     {"id": "dm101", "title": "Digital Marketing Foundations (synthetic)", "lessons": DM_LESSONS},
                     {"id": "ent201", "title": "Entrepreneurship Launchpad (synthetic)", "lessons": ENT_LESSONS},
                     {"id": "vip301", "title": "VIP Growth Lab (synthetic)", "access_note": "VIP-only (synthetic rule)",
                      "lessons": VIP_LESSONS},
                 ],
                 cohorts=[
                     {"key": "dm-b1", "name": "Digital Marketing Batch 1", "course": "dm101",
                      "starts_on": ist("2026-06-01 00:00"), "ends_on": ist("2026-08-31 23:59")},
                     {"key": "dm-b2", "name": "Digital Marketing Batch 2", "course": "dm101",
                      "starts_on": ist("2026-09-01 00:00"), "ends_on": ist("2026-12-31 23:59")},
                     {"key": "ent-b1", "name": "Entrepreneurship Batch 1", "course": "ent201",
                      "starts_on": ist("2026-09-15 00:00"), "ends_on": ist("2026-12-15 23:59")},
                 ],
                 cohort_memberships=[
                     {**p("m-meera", "2026-06-01 10:00", "2026-09-01 00:00"), "cohort": "dm-b1"},
                     *[{**p(mm), "cohort": "dm-b2"} for mm in
                       ["m-anika", "m-rahul", "m-vikram", "m-priya", "m-dev", "m-isha", "m-karthik", "m-nila"]],
                     {**p("m-new", "2026-10-16 10:00"), "cohort": "dm-b2"},
                     {**p("m-priya", "2026-09-15 10:00"), "cohort": "ent-b1"},
                     {**p("m-rahul2", "2026-09-15 10:00"), "cohort": "ent-b1"},
                 ],
                 access_periods=[
                     {**p("m-anika"), "label": "general"}, {**p("m-rahul"), "label": "annual"},
                     {**p("m-rahul2", "2026-09-15 10:00"), "label": "general"},
                     {**p("m-meera", "2026-06-01 10:00"), "label": "general"},  # alumnus, access continues
                     {**p("m-vikram"), "label": "general"},
                     {**p("m-sana"), "label": "annual"}, {**p("m-sana"), "label": "vip"},
                     {**p("m-priya"), "label": "annual"}, {**p("m-dev"), "label": "general"},
                     {**p("m-isha"), "label": "general"}, {**p("m-karthik"), "label": "general"},
                     {**p("m-nila"), "label": "general"}, {**p("m-new", "2026-10-16 10:00"), "label": "general"},
                 ],
                 entitlements=[
                     *[{**p(mm), "course": "dm101"} for mm in
                       ["m-anika", "m-rahul", "m-vikram", "m-sana", "m-priya", "m-dev", "m-isha", "m-karthik", "m-nila"]],
                     {**p("m-meera", "2026-06-01 10:00"), "course": "dm101"},
                     {**p("m-new", "2026-10-16 10:00"), "course": "dm101"},
                     {**p("m-priya", "2026-09-15 10:00"), "course": "ent201"},
                     {**p("m-rahul2", "2026-09-15 10:00"), "course": "ent201"},
                     {**p("m-sana"), "course": "vip301"},
                 ],
                 enrolments=[
                     *[{**p(mm), "course": "dm101", "cohort": "dm-b2"} for mm in
                       ["m-anika", "m-rahul", "m-vikram", "m-priya", "m-dev", "m-isha", "m-karthik", "m-nila"]],
                     {**p("m-new", "2026-10-16 10:00"), "course": "dm101", "cohort": "dm-b2"},
                     {**p("m-meera", "2026-06-01 10:00", "2026-09-01 00:00"), "course": "dm101", "cohort": "dm-b1"},
                     {**p("m-priya", "2026-09-15 10:00"), "course": "ent201", "cohort": "ent-b1"},
                     {**p("m-rahul2", "2026-09-15 10:00"), "course": "ent201", "cohort": "ent-b1"},
                     {**p("m-sana"), "course": "vip301"},
                 ],
                 lesson_deadlines=[
                     {"cohort": "dm-b1", "course": "dm101", "lesson": "dm-l1", "due_at": ist("2026-06-10 23:59")},
                     {"cohort": "dm-b1", "course": "dm101", "lesson": "dm-l2", "due_at": ist("2026-06-20 23:59")},
                     {"cohort": "dm-b2", "course": "dm101", "lesson": "dm-l1", "due_at": ist("2026-09-10 23:59")},
                     {"cohort": "dm-b2", "course": "dm101", "lesson": "dm-l2", "due_at": ist("2026-09-20 23:59")},
                     {"cohort": "dm-b2", "course": "dm101", "lesson": "dm-l3", "due_at": ist("2026-10-10 23:59")},
                     {"cohort": "dm-b2", "course": "dm101", "lesson": "dm-l5", "due_at": ist("2026-10-12 23:59")},
                     {"cohort": "dm-b2", "course": "dm101", "lesson": "dm-l6", "due_at": ist("2026-10-15 23:59")},
                     {"cohort": "ent-b1", "course": "ent201", "lesson": "ent-l1", "due_at": ist("2026-09-25 23:59")},
                     {"cohort": "ent-b1", "course": "ent201", "lesson": "ent-l2", "due_at": ist("2026-10-15 23:59")},
                 ],
                 assignments=[{"key": "dm-a1", "title": "Assignment 1: Customer persona", "cohort": "dm-b2",
                               "course": "dm101", "due_at": ist("2026-10-18 23:59"), "category": "Assignments"}])


def _post(id_, author, when, title, category="General", body=None):
    return {"id": id_, "author": author, "created_at": ist(when), "title": title, "category": category,
            "body": body or title, "url": f"/test/thread/{id_}"}


def _comment(id_, post, author, when, body, parent=None):
    return {"id": id_, "post": post, "parent": parent, "author": author, "created_at": ist(when), "body": body,
            "url": f"/test/thread/{post}#{id_}"}


def _like(id_, actor, ttype, target, when):
    return {"id": id_, "actor": actor, "target_type": ttype, "target": target, "created_at": ist(when)}


def discussions_bundle() -> dict:
    posts = [
        # earlier context
        _post("p-coach-old", "s-coach", "2026-10-10 09:00", "Week 6 kickoff", "Announcements"),
        _post("p-rahul-q", "m-rahul", "2026-10-16 10:00", "Ad account disabled — what now?", "Questions"),
        _post("p-vikram-a1", "m-vikram", "2026-10-16 18:00", "Assignment 1 — Vikram", "Assignments"),
        _post("p-vikram-q", "m-vikram", "2026-10-17 09:00", "Where is the persona template?", "Questions"),
        _post("p-priya-a1", "m-priya", "2026-10-17 11:00", "Assignment 1 — Priya", "Assignments"),
        _post("p-dev-q", "m-dev", "2026-10-18 10:00", "Pixel not firing on checkout page", "Questions"),
        # reporting day 2026-10-19 IST
        _post("p-sana-q", "m-sana", "2026-10-19 09:00", "Question about the VIP lab exercise", "Questions"),
        _post("p-coach-ann", "s-coach", "2026-10-19 09:30", "Live Q&A on Thursday", "Announcements"),
        _post("p-rahul-1", "m-rahul", "2026-10-19 10:15", "Tips on FB ads for local shops?"),
        _post("p-isha-q", "m-isha", "2026-10-19 11:00", "How do I set up the pixel?", "Questions"),
        _post("p-priya-win", "m-priya", "2026-10-19 12:00", "Got my first paying client!", "Wins"),
        _post("p-karthik-a1", "m-karthik", "2026-10-19 15:00", "Assignment 1 — Karthik", "Assignments"),
        _post("p-rahul-2", "m-rahul", "2026-10-19 16:00", "My ad results this week", body="CTR 1.2%"),
        _post("p-rahul-3", "m-rahul", "2026-10-19 18:00", "here's my work??"),
        _post("p-rahul-x", "m-rahul", "2026-10-19 23:50", "Late night thought"),  # 18:20 UTC → inside IST day
        # next IST day but still 2026-10-19 in UTC: must NOT count for the 19th
        _post("p-rahul-y", "m-rahul", "2026-10-20 00:10", "Just after midnight"),
    ]
    comments = [
        _comment("c-rahul2-old", "p-coach-old", "m-rahul2", "2026-10-10 12:00", "Excited for week 6"),
        _comment("c-coach-rq", "p-rahul-q", "s-coach", "2026-10-16 20:00", "Please appeal via Business Support."),
        _comment("c-mentor-vq", "p-vikram-q", "s-mentor", "2026-10-17 12:00", "It's in lesson 2 resources."),
        _comment("c-vikram-thanks", "p-vikram-q", "m-vikram", "2026-10-17 13:00", "Found it, solved, thanks!"),
        _comment("c-coach-sana", "p-sana-q", "s-coach", "2026-10-19 10:00", "Which exercise number do you mean?"),
        _comment("c-rahul-reopen", "p-rahul-q", "m-rahul", "2026-10-19 10:00", "Appeal rejected again, still stuck."),
        _comment("c-bot-isha", "p-isha-q", "b-eaglebot", "2026-10-19 11:05", "Thanks! A coach will look at this soon."),
        _comment("c-rahul-isha", "p-isha-q", "m-rahul", "2026-10-19 11:30", "I had the same issue, try the helper ext."),
        _comment("c-rahul-congrats", "p-priya-win", "m-rahul", "2026-10-19 12:30", "Congrats!!"),
        _comment("c-priya-reply", "p-priya-win", "m-priya", "2026-10-19 12:45", "Thank you!", parent="c-rahul-congrats"),
        _comment("c-coach-priya-fb", "p-priya-a1", "s-coach", "2026-10-19 14:00", "Great persona. Approved."),
    ]
    reactions = [
        _like("r-vikram-old", "m-vikram", "post", "p-coach-old", "2026-10-14 09:00"),
        _like("r1", "m-rahul", "post", "p-priya-win", "2026-10-19 12:31"),
        _like("r2", "m-rahul", "post", "p-isha-q", "2026-10-19 11:31"),
        _like("r3", "m-rahul", "post", "p-karthik-a1", "2026-10-19 15:10"),
        _like("r4", "m-priya", "comment", "c-rahul-congrats", "2026-10-19 12:46"),
        _like("r5", "m-isha", "comment", "c-rahul-isha", "2026-10-19 11:40"),
        _like("r6", "s-coach", "post", "p-priya-win", "2026-10-19 12:40"),
        _like("r8", "m-rahul", "post", "p-coach-ann", "2026-10-19 10:00"),
    ]
    q = lambda id_, mem, post, when, text, **kw: {"id": id_, "member": mem, "post": post, "asked_at": ist(when),  # noqa: E731
                                                   "text": text, **kw}
    ev = lambda id_, qid, kind, actor, when, note=None: {"id": id_, "question": qid, "kind": kind, "actor": actor,  # noqa: E731
                                                         "at": ist(when), "note": note}
    return _base(
        "discussions", "2026-10-20 02:00", "2026-09-20 00:00", "2026-10-20 00:00",
        posts=posts, comments=comments, reactions=reactions,
        submissions=[
            {"id": "sub-vikram", "assignment": "dm-a1", "member": "m-vikram", "post": "p-vikram-a1",
             "submitted_at": ist("2026-10-16 18:00")},
            {"id": "sub-priya", "assignment": "dm-a1", "member": "m-priya", "post": "p-priya-a1",
             "submitted_at": ist("2026-10-17 11:00")},
            {"id": "sub-karthik", "assignment": "dm-a1", "member": "m-karthik", "post": "p-karthik-a1",
             "submitted_at": ist("2026-10-19 15:00")},
            {"id": "sub-rahul-maybe", "assignment": None, "member": "m-rahul", "post": "p-rahul-3",
             "submitted_at": ist("2026-10-19 18:00"), "classification": "ambiguous"},
        ],
        feedback=[
            {"id": "fb-priya", "submission": "sub-priya", "reviewer": "s-coach", "reviewed_at": ist("2026-10-19 13:50"),
             "delivered_at": ist("2026-10-19 14:00"), "channel": "comment", "result": "pass"},
            {"id": "fb-vikram", "submission": "sub-vikram", "reviewer": "s-mentor", "reviewed_at": ist("2026-10-18 17:00")},
        ],
        wins=[{"post": "p-priya-win", "member": "m-priya", "category": "client"}],
        questions=[
            q("q-rahul", "m-rahul", "p-rahul-q", "2026-10-16 10:00", "Ad account disabled — what now?", assigned_to="s-coach"),
            q("q-vikram", "m-vikram", "p-vikram-q", "2026-10-17 09:00", "Where is the persona template?"),
            q("q-dev", "m-dev", "p-dev-q", "2026-10-18 10:00", "Pixel not firing on checkout page"),
            q("q-sana", "m-sana", "p-sana-q", "2026-10-19 09:00", "Question about the VIP lab exercise"),
            q("q-isha", "m-isha", "p-isha-q", "2026-10-19 11:00", "How do I set up the pixel?"),
        ],
        support_events=[
            ev("e1", "q-rahul", "assigned", "s-coach", "2026-10-16 10:30"),
            ev("e2", "q-rahul", "staff_response", "s-coach", "2026-10-16 20:00"),
            ev("e3", "q-rahul", "resolution_confirmed", "m-rahul", "2026-10-17 09:00", "Member said it worked"),
            ev("e4", "q-rahul", "reopened", "m-rahul", "2026-10-19 10:00", "Appeal rejected again"),
            ev("e5", "q-vikram", "staff_response", "s-mentor", "2026-10-17 12:00"),
            ev("e6", "q-vikram", "resolution_confirmed", "m-vikram", "2026-10-17 13:00", "Found it, solved"),
            ev("e7", "q-sana", "clarification_request", "s-coach", "2026-10-19 10:00"),
            ev("e8", "q-isha", "bot_response", "b-eaglebot", "2026-10-19 11:05", "Acknowledgement only"),
            ev("e9", "q-isha", "peer_response", "m-rahul", "2026-10-19 11:30"),
        ])


def progress_bundle() -> dict:
    def snap(mem, course, obs, done, total=None):
        totals = {"dm101": 6, "ent201": 4, "vip301": 3}
        return {"member": mem, "course": course, "observed_at": ist(obs), "completed_lesson_ids": done,
                "total_lessons": total or totals[course]}
    a, b = "2026-10-12 20:00", "2026-10-19 20:00"
    dm3 = ["dm-l1", "dm-l2", "dm-l3"]
    return _base("progress", "2026-10-20 02:00", "2026-10-12 00:00", "2026-10-20 00:00", progress=[
        snap("m-anika", "dm101", a, ["dm-l1", "dm-l2"]), snap("m-anika", "dm101", b, dm3 + ["dm-l4"]),
        snap("m-rahul", "dm101", a, ["dm-l1"]), snap("m-rahul", "dm101", b, ["dm-l1"]),
        snap("m-vikram", "dm101", a, ["dm-l1", "dm-l2"]), snap("m-vikram", "dm101", b, dm3),
        snap("m-priya", "dm101", a, dm3), snap("m-priya", "dm101", b, dm3),
        snap("m-priya", "ent201", b, ["ent-l1"]),
        snap("m-dev", "dm101", b, dm3), snap("m-karthik", "dm101", b, dm3),
        snap("m-isha", "dm101", a, dm3, total=6), snap("m-isha", "dm101", b, dm3, total=7),  # denominator changed
        snap("m-rahul2", "ent201", b, ["ent-l1", "ent-l2"]),
        snap("m-sana", "vip301", b, ["vip-l1"]),
        snap("m-meera", "dm101", "2026-08-30 20:00", ["dm-l1", "dm-l2"]),
        # m-nila: deliberately no progress data → must stay "unknown"
    ])


def leaderboard_bundle(observed: str, entries: list[tuple[str, int, int]], complete: bool) -> dict:
    return _base("leaderboard", observed, observed, observed,
                 leaderboard=[{"period": "30d", "complete": complete,
                               "entries": [{"member": mm, "rank": r, "points": p} for mm, r, p in entries]}])


def late_delta_bundle() -> dict:
    """Arrives after the 09:00 report for 2026-10-19: a late comment, an edit, a removed like and a duplicate."""
    d = discussions_bundle()
    edited = next(p for p in d["posts"] if p["id"] == "p-rahul-2")
    edited = {**edited, "body": "CTR 1.2% — edit: actually 1.4% after fixing the audience"}
    dup_like = next(r for r in d["reactions"] if r["id"] == "r1")
    removed = {**next(r for r in d["reactions"] if r["id"] == "r8"), "removed": True}
    return _base("discussions", "2026-10-20 12:00", "2026-10-19 00:00", "2026-10-20 12:00",
                 posts=[edited],
                 comments=[_comment("c-rahul-late", "p-rahul-2", "m-rahul", "2026-10-19 22:00", "Update coming tomorrow")],
                 reactions=[dup_like, removed])


def day2_bundles() -> dict[str, dict]:
    """2026-10-20 IST: discussions sync fails, then recovers."""
    failed = _base("discussions", "2026-10-21 02:00", "2026-10-20 00:00", "2026-10-21 00:00", status="failed",
                   error="HTTP 503 from source (simulated fault injection)")
    failed["coverage"]["status"] = "unknown"
    recovered = _base("discussions", "2026-10-21 10:00", "2026-10-20 00:00", "2026-10-21 00:00",
                      posts=[_post("p-anika-first", "m-anika", "2026-10-20 08:00", "Finished lesson 4 — loved it")],
                      reactions=[_like("r-karthik-anika", "m-karthik", "post", "p-anika-first", "2026-10-20 09:00")])
    membership = membership_bundle("2026-10-21 02:00", vikram_name="Vikram R.")  # renamed member
    progress = _base("progress", "2026-10-21 02:00", "2026-10-20 00:00", "2026-10-21 00:00", progress=[])
    return {"membership": membership, "progress": progress, "failed": failed, "recovered": recovered}


def total_outage_bundles() -> list[dict]:
    out = []
    for src in SOURCES:
        b = _base(src, "2026-10-22 02:00", "2026-10-21 00:00", "2026-10-22 00:00", status="failed",
                  error="network unreachable (simulated fault injection)")
        b["coverage"]["status"] = "unknown"
        out.append(b)
    return out


def initial_steps() -> list[tuple[datetime, dict]]:
    """Everything known by 2026-10-20 09:00 IST (the first scheduled report)."""
    return [
        (at("2026-10-12 21:00"), leaderboard_bundle("2026-10-12 21:00",
                                                    [("m-rahul", 1, 40), ("m-priya", 2, 22), ("m-isha", 3, 9)], True)),
        (at("2026-10-20 02:00"), membership_bundle()),
        (at("2026-10-20 02:00"), discussions_bundle()),
        (at("2026-10-20 02:00"), progress_bundle()),
        (at("2026-10-20 02:05"), leaderboard_bundle("2026-10-20 02:05",
                                                    [("m-rahul", 1, 52), ("m-priya", 2, 30)], False)),
    ]


def all_steps() -> list[tuple[datetime, dict]]:
    d2 = day2_bundles()
    return [*initial_steps(),
            (at("2026-10-20 12:00"), late_delta_bundle()),
            (at("2026-10-21 02:00"), d2["membership"]),
            (at("2026-10-21 02:00"), d2["progress"]),
            (at("2026-10-21 02:00"), d2["failed"]),
            (at("2026-10-21 10:00"), d2["recovered"]),
            *[(at("2026-10-22 02:00"), b) for b in total_outage_bundles()]]


def clone(b: dict) -> dict:
    return copy.deepcopy(b)


FIRST_REPORT_AT = at("2026-10-20 09:00")
