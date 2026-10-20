"""Printable per-member evidence report.

Shows a dated account of BOTH the member's recorded actions and the company's
recorded responses, with sources and coverage, so it can reveal missed learner
activity or missed company support. Privacy: other learners are never named
and their content is never included; staff/bot actors are identified by role
and name because they act for the company. Internal staff notes are excluded.
"""
from __future__ import annotations

from datetime import datetime

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import models as m
from app.config import CALC_VERSION, PROJECT_ROOT
from app.timeutil import fmt_local, iso

_env = Environment(loader=FileSystemLoader(PROJECT_ROOT / "app" / "web" / "templates"),
                   autoescape=select_autoescape(["html"]))


def _actor_label(s: Session, actor_id: int | None, subject_id: int) -> str:
    if actor_id is None:
        return "unknown"
    if actor_id == subject_id:
        return "this member"
    a = s.get(m.Member, actor_id)
    if a is None:
        return "unknown"
    if a.role in ("staff", "admin"):
        return f"staff: {a.display_name}"
    if a.role == "bot":
        return f"bot: {a.display_name}"
    return "another member"


def build_member_evidence(s: Session, member_id: int, now: datetime) -> dict:
    mem = s.get(m.Member, member_id)
    if mem is None:
        raise KeyError(member_id)
    c = s.get(m.Community, mem.community_id)
    assert c is not None
    timeline: list[dict] = []

    def add(when, kind, side, summary, ref=None, extra=None):
        timeline.append({"at": iso(when), "at_local": fmt_local(when), "kind": kind, "side": side,
                         "summary": summary, "source_ref": ref, **(extra or {})})

    for p in s.scalars(select(m.Post).where(m.Post.author_id == member_id)):
        add(p.created_at, "post", "member", f"Posted '{p.title}' in {p.category or 'uncategorised'}", p.source_ref,
            {"version": p.version, "deleted_confirmed": bool(p.deleted_confirmed_at)})
    for cm in s.scalars(select(m.Comment).where(m.Comment.author_id == member_id)):
        add(cm.created_at, "comment", "member", "Commented", cm.source_ref, {"version": cm.version})
    given = s.scalars(select(m.Reaction).where(m.Reaction.actor_id == member_id)).all()
    received = s.scalars(select(m.Reaction).where(m.Reaction.target_author_id == member_id)).all()
    for sn in s.scalars(select(m.ProgressSnapshot).where(m.ProgressSnapshot.member_id == member_id)
                        .order_by(m.ProgressSnapshot.observed_at)):
        course = s.get(m.Course, sn.course_id)
        add(sn.observed_at, "progress_observation", "record",
            f"{course.title if course else sn.course_id}: {sn.completed_lessons}/{sn.total_lessons} lessons marked complete", sn.source_ref)
    for sub in s.scalars(select(m.Submission).where(m.Submission.member_id == member_id)):
        a = s.get(m.AssignmentDef, sub.assignment_id) if sub.assignment_id else None
        add(sub.submitted_at, "assignment_submitted", "member",
            f"Submitted {a.title if a else 'possible submission (classification: ' + sub.classification + ')'}",
            sub.source_ref)
        for fb in s.scalars(select(m.Feedback).where(m.Feedback.submission_id == sub.id)):
            if fb.reviewed_at:
                add(fb.reviewed_at, "assignment_reviewed", "company", f"Reviewed by {_actor_label(s, fb.reviewer_id, member_id)}",
                    fb.source_ref)
            if fb.feedback_delivered_at:
                add(fb.feedback_delivered_at, "feedback_delivered", "company",
                    f"Feedback delivered via {fb.feedback_channel} by {_actor_label(s, fb.reviewer_id, member_id)}"
                    + (f"; result: {fb.assessment_result}" if fb.assessment_result else ""), fb.source_ref)
    for w in s.scalars(select(m.Win).where(m.Win.member_id == member_id)):
        add(w.recorded_at, "win", "member", f"Shared a win ({w.category or 'uncategorised'}; {w.verification})", w.source_ref)
    for q in s.scalars(select(m.SupportQuestion).where(m.SupportQuestion.member_id == member_id)):
        add(q.asked_at, "question_asked", "member", f"Asked: {q.text}", q.source_ref)
        for e in s.scalars(select(m.SupportEvent).where(m.SupportEvent.question_id == q.id)):
            side = "company" if e.kind in ("staff_response", "clarification_request", "assigned", "bot_response") else (
                "member" if e.actor_id == member_id else "peer")
            # Peer notes are omitted: they are another member's content.
            note_ok = e.note and (e.actor_id == member_id or side == "company")
            add(e.at, f"support:{e.kind}", side, f"{e.kind.replace('_', ' ')} by {_actor_label(s, e.actor_id, member_id)}"
                + (f" — {e.note}" if note_ok else ""), e.source_ref, {"question": q.source_question_id})
    timeline.sort(key=lambda r: (r["at"] or "", r["kind"]))

    cohorts = s.execute(select(m.CohortMembership, m.Cohort).join(m.Cohort).where(m.CohortMembership.member_id == member_id)).all()
    plans = s.scalars(select(m.AccessPeriod).where(m.AccessPeriod.member_id == member_id)).all()
    ents = s.execute(select(m.Entitlement, m.Course).join(m.Course).where(m.Entitlement.member_id == member_id)).all()
    aliases = s.scalars(select(m.MemberAlias.display_name).where(m.MemberAlias.member_id == member_id)).all()
    runs = s.scalars(select(m.SyncRun).where(
        m.SyncRun.community_id == c.id,
        or_(m.SyncRun.status == "failed", m.SyncRun.coverage_status != "complete"))).all()
    corrections = s.scalars(select(m.AuditLog).where(m.AuditLog.entity_type == "member", m.AuditLog.entity_id == member_id)).all()
    return {
        "generated_at_utc": iso(now), "calc_version": CALC_VERSION,
        "community": {"name": c.name, "synthetic": c.is_synthetic},
        "member": {"name": mem.display_name, "source_member_id": mem.source_member_id, "role": mem.role,
                   "joined_at": iso(mem.joined_at), "previous_names": sorted(set(aliases) - {mem.display_name})},
        "batches": [{"cohort": co.name, "from": iso(cm.valid_from), "to": iso(cm.valid_to)} for cm, co in cohorts],
        "plan_labels": [{"label": p.label, "status": p.status, "from": iso(p.valid_from), "to": iso(p.valid_to)} for p in plans],
        "course_access": [{"course": co.title, "from": iso(e.valid_from), "to": iso(e.valid_to)} for e, co in ents],
        "likes": {"given_total": sum(1 for r in given if not r.removed_confirmed_at),
                  "received_total": sum(1 for r in received if not r.removed_confirmed_at),
                  "removed_given": sum(1 for r in given if r.removed_confirmed_at)},
        "timeline": timeline,
        "coverage_limitations": [{"source": r.source_name, "status": r.status, "coverage": r.coverage_status,
                                  "from": iso(r.coverage_start), "to": iso(r.coverage_end), "error": r.error} for r in runs],
        "corrections": [{"field": a.field, "old": a.old_value, "new": a.new_value, "reason": a.reason, "by": a.actor,
                         "at": iso(a.at)} for a in corrections],
        "notes": [
            "This is a record of captured observations, not a complete account of everything that happened.",
            "Absence of a record during a coverage gap means nothing was observed, not that nothing happened.",
            "Lesson completion markers are recorded completion, not proof of viewing time or understanding.",
            "Staff replies or bot acknowledgements are not resolution; only confirmed resolution is shown as resolved.",
            "Other members are not identified in this export.",
        ],
    }


def render_member_html(payload: dict) -> str:
    return _env.get_template("member_evidence.html").render(p=payload)
