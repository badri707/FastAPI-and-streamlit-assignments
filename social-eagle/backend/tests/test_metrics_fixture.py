"""Known-fixture analytics: hand-computed expected values (see comments) must match exactly."""
from __future__ import annotations

from datetime import date, datetime

from app import clock, db
from app.connectors.factory import get_adapter, get_store
from app.models import Member
from app.services import metrics, sync

T = "2026-03-{}"


def _m(uid, group, name, role="member", tier="general", joined="2026-03-01T00:00:00", **kw):
    row = {"upstream_id": uid, "group_id": group, "display_name": name, "email": f"{uid}@example.com", "role": role,
           "tier": tier, "joined_at": joined, "left_at": None, "status": "active", "is_bot": 1 if role == "bot" else 0,
           "is_staff": 1 if role in ("admin", "moderator") else 0, "rejoin_count": 0, "onboarding_status": "done", "tags": "[]"}
    row.update(kw)
    return row


def _p(uid, author, created, kind="post", parent=None, title=None, body="text", category=None, group="G", deleted=None):
    return {"upstream_id": uid, "group_id": group, "author_id": author, "parent_id": parent, "root_id": parent,
            "kind": kind, "title": title, "body": body, "category": category, "created_at": created, "edited_at": None,
            "deleted_at": deleted, "version": 1, "client_ref": None, "is_automated": 0}


def build_fixture():
    st = get_store()
    feed = [
        ("group", {"upstream_id": "G", "name": "Fixture main"}), ("group", {"upstream_id": "H", "name": "Fixture other"}),
        ("member", _m("A", "G", "Asha")), ("member", _m("B", "G", "Bala", tier="annual")),
        ("member", _m("S", "G", "Staff", role="moderator")), ("member", _m("BOT", "G", "Bot", role="bot")),
        ("member", _m("D", "G", "Dev", status="left", left_at="2026-03-08T10:00:00")), ("member", _m("H1", "H", "Other")),
        ("course", {"upstream_id": "C1", "group_id": "G", "title": "Course", "description": "", "access_tiers": "general,annual"}),
        ("lesson", {"upstream_id": "L1", "course_id": "C1", "title": "L1", "module": "M", "position": 1, "video_minutes": 5}),
        ("lesson", {"upstream_id": "L2", "course_id": "C1", "title": "L2", "module": "M", "position": 2, "video_minutes": 5}),
        # p1 at 23:59 IST Mar 8; p2 at 00:01 IST Mar 9 (day-boundary check)
        ("post", _p("p1", "A", "2026-03-08T18:29:00", title="How do I X?", body="How do I X?", category="Questions")),
        ("post", _p("p2", "A", "2026-03-08T18:31:00", title="Hello", body="Sharing my week", category="General")),
        ("post", _p("p1", "A", "2026-03-08T18:29:00", title="How do I X?", body="How do I X?", category="Questions")),  # duplicate
        ("post", _p("c1", "B", "2026-03-08T20:29:00", kind="comment", parent="p1", body="Try lesson 1")),  # 01:59 IST Mar 9
        ("post", _p("c2", "S", "2026-03-09T05:00:00", kind="comment", parent="p2", body="Welcome")),  # staff
        ("post", _p("p3", "B", "2026-03-09T06:00:00", title="Why Y?", body="Why Y?", category="Questions")),
        ("post", _p("c3", "B", "2026-03-09T06:30:00", kind="comment", parent="p3", body="Still wondering")),  # asker follow-up
        ("post", _p("p4", "A", "2026-03-09T07:00:00", title="Old", body="remove me", category="General")),
        ("post", _p("p4", "A", "2026-03-09T07:00:00", title="Old", body="remove me", category="General", deleted="2026-03-09T08:00:00")),
        ("post", _p("h1", "H1", "2026-03-09T07:00:00", title="Other group?", body="Other group?", category="Questions", group="H")),
        ("reaction", {"upstream_id": "r1", "group_id": "G", "post_id": "p2", "member_id": "B", "kind": "like", "created_at": "2026-03-09T10:00:00", "deleted_at": None}),
        ("reaction", {"upstream_id": "r1", "group_id": "G", "post_id": "p2", "member_id": "B", "kind": "like", "created_at": "2026-03-09T10:00:00", "deleted_at": None}),
        ("reaction", {"upstream_id": "r2", "group_id": "G", "post_id": "p1", "member_id": "S", "kind": "like", "created_at": "2026-03-09T10:00:00", "deleted_at": None}),
        # progress: newer 'completed' arrives before an older 'uncompleted' (late event must not win)
        ("progress", {"upstream_id": "e2", "member_id": "A", "lesson_id": "L1", "kind": "completed", "occurred_at": "2026-03-09T09:00:00"}),
        ("progress", {"upstream_id": "e1", "member_id": "A", "lesson_id": "L1", "kind": "uncompleted", "occurred_at": "2026-03-09T08:00:00"}),
        ("progress", {"upstream_id": "e2", "member_id": "A", "lesson_id": "L1", "kind": "completed", "occurred_at": "2026-03-09T09:00:00"}),
        # SYNTHETIC sessions for A: 03:00-03:20 and 03:10-03:40 overlap -> 40 min; 05:00 start without stop -> capped 30
        ("session", {"upstream_id": "s1", "member_id": "A", "kind": "start", "at": "2026-03-09T03:00:00"}),
        ("session", {"upstream_id": "s2", "member_id": "A", "kind": "stop", "at": "2026-03-09T03:20:00"}),
        ("session", {"upstream_id": "s3", "member_id": "A", "kind": "start", "at": "2026-03-09T03:10:00"}),
        ("session", {"upstream_id": "s4", "member_id": "A", "kind": "stop", "at": "2026-03-09T03:40:00"}),
        ("session", {"upstream_id": "s5", "member_id": "A", "kind": "start", "at": "2026-03-09T05:00:00"}),
    ]
    with st.connect() as c:
        for entity, row in feed:
            st.upsert(c, entity, row)


def setup_fixture():
    with db.session_scope() as s:
        clock.freeze(s, datetime(2026, 3, 10, 12, 0))
    build_fixture()
    with db.session_scope() as s:
        res = sync.sync_once(s, get_adapter("simulator"))
    assert res["ok"] and res["remaining_deferred"] == 0, res
    return res


def gid(s, up="G"):
    from app.models import Group
    return s.query(Group).filter_by(upstream_id=up).one().id


def test_contributions_ist_boundaries_duplicates_staff_and_isolation(fresh):
    setup_fixture()
    with db.session_scope() as s:
        sc = metrics.Scope(group_id=gid(s), start=date(2026, 3, 8), end=date(2026, 3, 9))
        c = metrics.contributions(s, sc)
        assert (c["posts"], c["comments"], c["reactions"]) == (3, 2, 1)  # p1,p2,p3 / c1,c3 / r1
        assert c["distinct_contributors"] == 2  # A, B
        assert c["active_contribution_days"] == 3  # A: Mar 8 + Mar 9; B: Mar 9
        assert c["daily"]["2026-03-08"] == {"posts": 1, "comments": 0, "reactions": 0, "contributors": 1}
        assert c["daily"]["2026-03-09"] == {"posts": 2, "comments": 2, "reactions": 1, "contributors": 2}
        assert c["separate"] == {"staff_posts_and_comments": 1, "bot_posts_and_comments": 0}
        only9 = metrics.contributions(s, metrics.Scope(group_id=gid(s), start=date(2026, 3, 9), end=date(2026, 3, 9)))
        assert only9["posts"] == 2
        with_staff = metrics.contributions(s, metrics.Scope(group_id=gid(s), start=date(2026, 3, 8), end=date(2026, 3, 9), include_staff=True))
        assert (with_staff["comments"], with_staff["reactions"]) == (3, 2)
        other = metrics.contributions(s, metrics.Scope(group_id=gid(s, "H"), start=date(2026, 3, 8), end=date(2026, 3, 9)))
        assert other["posts"] == 1 and other["distinct_contributors"] == 1


def test_members_support_and_response_times(fresh):
    setup_fixture()
    with db.session_scope() as s:
        sc = metrics.Scope(group_id=gid(s), start=date(2026, 3, 8), end=date(2026, 3, 9))
        m = metrics.member_totals(s, sc)
        assert m["active_members"] == 2 and m["left_in_range"] == 1 and m["staff"] == 1
        sup = metrics.support_metrics(s, sc)
        assert sup["unanswered_now"] == 1  # p3: only the asker followed up
        assert sup["questions_in_range"] == 2
        assert sup["first_response"]["median_hours"] == 2.0  # c1 two hours after p1
        assert sup["first_response_by"]["member"]["n"] == 1


def test_late_progress_event_does_not_override_and_time_spent_rules(fresh):
    setup_fixture()
    with db.session_scope() as s:
        a = s.query(Member).filter_by(upstream_id="A").one()
        b = s.query(Member).filter_by(upstream_id="B").one()
        from app.models import LessonCompletion, ProgressEvent

        lc = s.query(LessonCompletion).filter_by(member_id=a.id).one()
        assert lc.completed is True  # older 'uncompleted' (late) did not win
        assert s.query(ProgressEvent).filter_by(member_id=a.id).count() == 2  # duplicate delivery ignored
        ts = metrics.time_spent(s, a.id, datetime(2026, 3, 9), datetime(2026, 3, 10))
        assert ts["minutes"] == 70.0 and ts["capped_sessions"] == 1 and ts["sessions"] == 2
        assert metrics.time_spent(s, b.id, datetime(2026, 3, 9), datetime(2026, 3, 10)) == {
            "status": "unavailable", "minutes": None,
            "note": "No session events observed for this member/period. Time spent is unknown — not zero."}


def test_resync_is_idempotent(fresh):
    setup_fixture()
    with db.session_scope() as s:
        before = metrics.contributions(s, metrics.Scope(group_id=gid(s), start=date(2026, 3, 8), end=date(2026, 3, 9)))
        res = sync.sync_once(s, get_adapter("simulator"))
        assert res["applied"] == 0
        after = metrics.contributions(s, metrics.Scope(group_id=gid(s), start=date(2026, 3, 8), end=date(2026, 3, 9)))
        assert before == after


def test_coverage_notes_incomplete_and_unknown_history(fresh):
    setup_fixture()
    with db.session_scope() as s:
        cov = metrics.coverage(s, metrics.Scope(group_id=gid(s), start=date(2026, 3, 1), end=date(2026, 3, 10)))
        assert any("incomplete" in n for n in cov["notes"])
        assert any("No observations before 2026-03-08" in n for n in cov["notes"])
