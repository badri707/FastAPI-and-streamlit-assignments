"""The twelve business scenarios from spec section 1A, on the SYNTHETIC workspace."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from app import fixtures as fx
from app import models as m
from app.config import Mode
from app.connectors.importer import ingest_bundle
from app.db import session_scope
from app.reports.daily import build_report, issue_report
from app.reports.member_export import build_member_evidence
from app.retrieval import rebuild_index, search_lessons
from tests import expected as ex
from tests.conftest import community, ingest_steps

D = date(2026, 10, 19)


def report(engine, settings, when=fx.FIRST_REPORT_AT, day=D):
    with session_scope(engine) as s:
        return build_report(s, community(s), day, day, when, settings)


def by_member(rows, sid):
    return [r for r in rows if r["member"]["source_member_id"] == sid]


def test_report_complete_and_reconciles_with_raw_records(seeded, settings):
    p = report(seeded, settings)
    assert p["status"] == "complete"
    exp = ex.participation([fx.discussions_bundle()], "2026-10-19")
    got = p["sections"]["participation"]["interval"]["totals_learners"]
    assert {k: got[k] for k in exp} == exp
    # concrete numbers so a reviewer can check by hand
    assert exp == {"posts": 8, "comments": 4, "likes_given": 6, "likes_received": 6}


def test_ist_midnight_boundary(seeded, settings):
    p = report(seeded, settings)
    rahul = next(v for v in p["sections"]["participation"]["interval"]["per_member"].values()
                 if v["member"]["source_member_id"] == "m-rahul")
    # rahul-1, rahul-2, rahul-3, rahul-x (23:50 IST) count; rahul-y (00:10 IST next day, same UTC date) does not
    assert rahul["posts"] == 4
    p20 = report(seeded, settings, day=date(2026, 10, 20))
    assert p20["status"] == "unavailable"  # no source covers 10-20 yet → not zero activity
    assert "totals_learners" not in p20["sections"]["participation"]


def test_s1_quiet_but_learning(seeded, settings):
    p = report(seeded, settings)
    anika = by_member(p["sections"]["learning"]["enrolments"], "m-anika")[0]
    assert (anika["completed"], anika["total"], anika["change_status"], anika["change"]) == (4, 6, "comparable", 2)
    assert "m-anika" not in {r["member"]["source_member_id"] for r in p["sections"]["outreach"]["outreach_candidates"]}
    pm = p["sections"]["participation"]["interval"]["per_member"]
    assert all(v["member"]["source_member_id"] != "m-anika" for v in pm.values())


def test_s2_interactive_with_little_progress(seeded, settings):
    p = report(seeded, settings)
    rahul = by_member(p["sections"]["learning"]["enrolments"], "m-rahul")[0]
    assert (rahul["completed"], rahul["change"]) == (1, 0)
    overdue = {d["lesson"] for d in by_member(p["sections"]["learning"]["deadline_checks"], "m-rahul")
               if d["status"] == "overdue"}
    assert overdue == {"dm-l2", "dm-l3"}
    cand = by_member(p["sections"]["outreach"]["outreach_candidates"], "m-rahul")[0]
    assert len(cand["reasons"]) == 2


def test_s3_alumnus_keeps_access_without_current_deadlines(seeded, settings):
    with session_scope(seeded) as s:
        from app.analytics import metrics as mx
        from app.timeutil import local_day_bounds_utc
        st, en = local_day_bounds_utc(D)
        ctx = mx.Ctx(s, community(s), st, en, fx.FIRST_REPORT_AT, settings)
        ctx.load_members()
        status = mx.member_status(ctx)
        meera = next(v for k, v in status.items() if ctx.members[k].source_member_id == "m-meera")
    assert meera["batch_status"] == "alumni" and meera["plans"] == ["general"]
    p = report(seeded, settings)
    checks = by_member(p["sections"]["learning"]["deadline_checks"], "m-meera")
    assert {c["cohort"] for c in checks} == {"dm-b1"}  # no Batch 2 deadlines inherited
    assert all(c["status"] == "completed_marker_recorded" for c in checks)


def test_s4_vip_course_excluded_for_general_member(seeded, settings):
    p = report(seeded, settings)
    vikram_courses = {r["course"] for r in by_member(p["sections"]["learning"]["enrolments"], "m-vikram")}
    assert vikram_courses == {"dm101"}
    sana_courses = {r["course"] for r in by_member(p["sections"]["learning"]["enrolments"], "m-sana")}
    assert "vip301" in sana_courses
    with session_scope(seeded) as s:
        rebuild_index(s)
        vikram = s.scalar(select(m.Member).where(m.Member.source_member_id == "m-vikram"))
        sana = s.scalar(select(m.Member).where(m.Member.source_member_id == "m-sana"))
        q = "high-ticket pricing playbook"
        assert search_lessons(s, q, vikram.id, fx.FIRST_REPORT_AT) == []
        assert any("VIP" in r["course"] for r in search_lessons(s, q, sana.id, fx.FIRST_REPORT_AT))


def test_s5_two_enrolments_different_deadlines(seeded, settings):
    p = report(seeded, settings)
    priya = by_member(p["sections"]["learning"]["deadline_checks"], "m-priya")
    by = {(c["cohort"], c["lesson"]): c["status"] for c in priya}
    assert by[("dm-b2", "dm-l3")] == "completed_marker_recorded"
    assert by[("ent-b1", "ent-l2")] == "overdue"
    assert {r["course"] for r in by_member(p["sections"]["learning"]["enrolments"], "m-priya")} == {"dm101", "ent201"}


def test_s6_unanswered_question_overdue(seeded, settings):
    sp = report(seeded, settings)["sections"]["support"]
    dev = by_member(sp["unresolved"], "m-dev")[0]
    assert dev["first_staff_response_at"] is None and dev["first_response_target_breached"]
    assert dev["age_hours"] == 38.0
    assert [b["source_question_id"] for b in sp["target_breaches_open"]] == ["q-dev"]


def test_s7_peer_and_bot_ack_not_resolution(seeded, settings):
    sp = report(seeded, settings)["sections"]["support"]
    isha = by_member(sp["unresolved"], "m-isha")[0]
    assert (isha["peer_responses"], isha["bot_responses"], isha["state_from_evidence"]) == (1, 1, "awaiting_staff")
    assert isha["first_staff_response_at"] is None
    rahul = by_member(sp["unresolved"], "m-rahul")[0]  # resolved, then reopened
    assert rahul["reopened_count"] == 1 and rahul["state_from_evidence"] == "awaiting_staff"
    sana = by_member(sp["unresolved"], "m-sana")[0]
    assert sana["state_from_evidence"] == "awaiting_member"
    assert not by_member(sp["unresolved"], "m-vikram")  # genuinely resolved
    assert (sp["new_count"], len(sp["unresolved"]), sp["unresolved_awaiting_staff"]) == (2, 4, 3)


def test_s8_assignment_awaiting_feedback(seeded, settings):
    a = report(seeded, settings)["sections"]["assignments"]
    assert [r["member"]["source_member_id"] for r in a["submitted_in_interval"]] == ["m-karthik"]
    assert [r["member"]["source_member_id"] for r in a["awaiting_review"]] == ["m-karthik"]
    assert [r["member"]["source_member_id"] for r in a["feedback_delivered_in_interval"]] == ["m-priya"]
    assert [r["member"]["source_member_id"] for r in a["reviewed_feedback_not_delivered"]] == ["m-vikram"]
    assert [r["member"]["source_member_id"] for r in a["ambiguous_classification_needs_review"]] == ["m-rahul"]


def test_s9_missing_progress_stays_unknown(seeded, settings):
    p = report(seeded, settings)
    nila = by_member(p["sections"]["learning"]["enrolments"], "m-nila")[0]
    assert nila["progress"] == "unknown" and nila["completed"] is None
    assert {c["status"] for c in by_member(p["sections"]["learning"]["deadline_checks"], "m-nila")} == \
        {"unknown_no_progress_data"}
    isha = by_member(p["sections"]["learning"]["enrolments"], "m-isha")[0]
    assert isha["change_status"] == "not_comparable"  # denominator changed 6 → 7


def test_s10_duplicates_removed_likes_edits_late_records(seeded, settings):
    with session_scope(seeded) as s:
        before = s.scalar(select(func.count()).select_from(m.Post))
        run = ingest_bundle(s, fx.clone(fx.discussions_bundle()), Mode.TEST, fx.at("2026-10-20 03:00"))
        assert run.records_new == 0 and run.records_changed == 0
        assert s.scalar(select(func.count()).select_from(m.Post)) == before
    with session_scope(seeded) as s:
        r1, created = issue_report(s, community(s), D, D, fx.FIRST_REPORT_AT, settings, "scheduled")
        assert created and r1.revision == 1
    ingest_steps(seeded, [(fx.at("2026-10-20 12:00"), fx.late_delta_bundle())])
    with session_scope(seeded) as s:
        post = s.scalar(select(m.Post).where(m.Post.source_post_id == "p-rahul-2"))
        versions = s.scalars(select(m.ContentVersion).where(m.ContentVersion.entity_type == "post",
                                                            m.ContentVersion.entity_id == post.id)).all()
        assert post.version == 2 and [v.excerpt for v in versions][0] == "CTR 1.2%"
        r2, created = issue_report(s, community(s), D, D, fx.at("2026-10-20 12:30"), settings, "manual")
        assert created and r2.revision == 2 and r2.supersedes_id == r1.id
        assert "participation data changed" in r2.revision_reason
        old = s.get(m.ReportRun, r1.id)
        assert old.payload["sections"]["participation"]["interval"]["totals_learners"]["comments"] == 4  # unchanged
    exp = ex.participation([fx.discussions_bundle(), fx.late_delta_bundle()], "2026-10-19", removed_ids={"r8"})
    got = r2.payload["sections"]["participation"]["interval"]
    assert {k: got["totals_learners"][k] for k in exp} == exp
    assert got["excluded_removed_likes"] == 1


def test_s11_failed_sync_then_recovery_no_false_inactivity(seeded, settings):
    d2 = fx.day2_bundles()
    ingest_steps(seeded, [(fx.at("2026-10-21 02:00"), d2["membership"]), (fx.at("2026-10-21 02:00"), d2["progress"]),
                          (fx.at("2026-10-21 02:00"), d2["failed"])])
    day = date(2026, 10, 20)
    with session_scope(seeded) as s:
        r1, _ = issue_report(s, community(s), day, day, fx.at("2026-10-21 09:00"), settings, "scheduled")
        assert r1.status == "degraded"
        part = r1.payload["sections"]["participation"]
        assert part["availability"] == "unavailable" and "totals_learners" not in part
        assert r1.payload["sections"]["outreach"]["availability"] == "unavailable"
        again, created = issue_report(s, community(s), day, day, fx.at("2026-10-21 09:05"), settings, "manual")
        assert not created and again.id == r1.id  # retry does not duplicate
        assert s.scalar(select(func.count()).select_from(m.OutboxMessage)) == 1
    ingest_steps(seeded, [(fx.at("2026-10-21 10:00"), d2["recovered"])])
    with session_scope(seeded) as s:
        r2, created = issue_report(s, community(s), day, day, fx.at("2026-10-21 10:05"), settings, "manual")
        assert created and r2.revision == 2 and r2.status == "complete"
        tot = r2.payload["sections"]["participation"]["interval"]["totals_learners"]
        exp = ex.participation([fx.discussions_bundle(), fx.late_delta_bundle(), d2["recovered"]], "2026-10-20",
                               removed_ids={"r8"})
        assert {k: tot[k] for k in exp} == exp == {"posts": 2, "comments": 0, "likes_given": 1, "likes_received": 1}
        # renamed member keeps identity
        vik = s.scalar(select(m.Member).where(m.Member.source_member_id == "m-vikram"))
        assert vik.display_name == "Vikram R."
        assert s.scalar(select(func.count()).select_from(m.Member).where(m.Member.source_member_id == "m-vikram")) == 1
    for b in fx.total_outage_bundles():
        ingest_steps(seeded, [(fx.at("2026-10-22 02:00"), b)])
    with session_scope(seeded) as s:
        r3, _ = issue_report(s, community(s), date(2026, 10, 21), date(2026, 10, 21), fx.at("2026-10-22 09:00"),
                             settings, "scheduled")
        assert r3.status == "unavailable"


def test_s12_member_export_reconciles_and_is_private(seeded, settings):
    with session_scope(seeded) as s:
        rahul = s.scalar(select(m.Member).where(m.Member.source_member_id == "m-rahul"))
        ev = build_member_evidence(s, rahul.id, fx.FIRST_REPORT_AT)
    raw = fx.discussions_bundle()
    assert sum(1 for t in ev["timeline"] if t["kind"] == "post") == sum(1 for p in raw["posts"] if p["author"] == "m-rahul")
    assert sum(1 for t in ev["timeline"] if t["kind"] == "comment") == \
        sum(1 for c in raw["comments"] if c["author"] == "m-rahul")
    assert ev["likes"]["given_total"] == sum(1 for r in raw["reactions"] if r["actor"] == "m-rahul")
    text = str(ev)
    for other in ("Priya", "Isha", "Anika", "Dev", "Karthik"):
        assert other not in text
    assert "staff: Coach Kavya" in text  # company responses are visible
    kinds = {t["kind"] for t in ev["timeline"]}
    assert {"support:staff_response", "support:reopened", "question_asked"} <= kinds


def test_duplicate_display_names_are_distinct_members(seeded, settings):
    with session_scope(seeded) as s:
        rows = s.scalars(select(m.Member).where(m.Member.display_name == "Rahul S.")).all()
        assert {r.source_member_id for r in rows} == {"m-rahul", "m-rahul2"}


def test_outreach_list_is_rule_based(seeded, settings):
    o = report(seeded, settings)["sections"]["outreach"]
    assert {c["member"]["source_member_id"] for c in o["outreach_candidates"]} == {"m-dev", "m-nila", "m-priya", "m-rahul"}
    nila = by_member(o["outreach_candidates"], "m-nila")[0]
    assert "progress data unknown" in nila["reasons"][0]
