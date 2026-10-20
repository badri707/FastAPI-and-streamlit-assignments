"""Deterministic metric definitions (see docs/METRIC_DICTIONARY.md).

Every function takes an explicit interval [start, end) in naive UTC and a data
``cutoff``: records observed after the cutoff are ignored, so a report can be
regenerated exactly as it would have looked at that time.

Bulk queries per table (bounded by community) are used instead of one query
per member.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.config import Settings
from app.timeutil import iso, local_date_of, working_hours_between

UNAVAILABLE = "unavailable"

# Which expected source each report section depends on.
SECTION_SOURCES = {
    "membership": "membership",
    "participation": "discussions",
    "wins": "discussions",
    "support": "discussions",
    "assignments": "discussions",
    "learning": "progress",
}
# Leaderboard is snapshot-based: each snapshot carries its own observation time and completeness,
# so it is reported as observed rather than gated on interval coverage.


@dataclass
class Ctx:
    s: Session
    community: m.Community
    start: datetime
    end: datetime
    cutoff: datetime
    settings: Settings
    members: dict[int, m.Member] = field(default_factory=dict)

    @property
    def as_of(self) -> datetime:
        """States (ages, breaches, active periods) are evaluated at the end of the interval,
        using only data observed by the cutoff, so re-running a report is reproducible."""
        return min(self.end, self.cutoff)

    def load_members(self) -> None:
        rows = self.s.scalars(select(m.Member).where(m.Member.community_id == self.community.id,
                                                     m.Member.first_observed_at <= self.cutoff)).all()
        self.members = {r.id: r for r in rows}

    def is_learner(self, member_id: int | None) -> bool:
        mem = self.members.get(member_id) if member_id else None
        return mem is not None and mem.role == "member"

    def ref(self, member_id: int | None) -> dict | None:
        mem = self.members.get(member_id) if member_id else None
        if mem is None:
            return None
        return {"member_id": mem.id, "source_member_id": mem.source_member_id, "name": mem.display_name, "role": mem.role}


def _active(valid_from: datetime | None, valid_to: datetime | None, at: datetime) -> bool:
    return (valid_from is None or valid_from <= at) and (valid_to is None or valid_to > at)


# ---------------------------------------------------------------- data health

def source_health(ctx: Ctx) -> dict:
    expected = ctx.community.expected_sources or []
    runs = ctx.s.scalars(select(m.SyncRun).where(m.SyncRun.community_id == ctx.community.id,
                                                 m.SyncRun.started_at <= ctx.cutoff)
                         .order_by(m.SyncRun.started_at)).all()
    by_source: dict[str, list[m.SyncRun]] = defaultdict(list)
    for r in runs:
        by_source[r.source_name].append(r)
    out = {}
    for src in expected:
        rs = by_source.get(src, [])
        covering = [r for r in rs if r.status in ("success", "partial") and r.coverage_start is not None
                    and r.coverage_end is not None and r.coverage_start <= ctx.start and r.coverage_end >= ctx.end]
        complete = [r for r in covering if r.status == "success" and r.coverage_status == "complete"]
        failures = [r for r in rs if r.status == "failed"]
        last_ok = max((r for r in rs if r.status in ("success", "partial")), key=lambda r: r.started_at, default=None)
        if complete:
            state = "ok"
        elif covering:
            state = "partial"
        elif failures:
            state = "failed"
        elif rs:
            state = "not_covering_interval"
        else:
            state = "missing"
        gaps = sorted({g for r in covering for g in (r.known_gaps or [])})
        out[src] = {
            "state": state,
            "last_success_at": iso(last_ok.finished_at) if last_ok else None,
            "last_failure_at": iso(failures[-1].started_at) if failures else None,
            "last_failure_error": failures[-1].error if failures else None,
            "covering_run_ids": [r.id for r in covering],
            "known_gaps": gaps,
        }
    return out


def section_availability(health: dict) -> dict[str, str]:
    """ok | partial | unavailable per report section."""
    out = {}
    for section, src in SECTION_SOURCES.items():
        h = health.get(src)
        if h is None:
            out[section] = "not_configured"
        elif h["state"] == "ok":
            out[section] = "ok"
        elif h["state"] == "partial":
            out[section] = "partial"
        else:
            out[section] = UNAVAILABLE
    return out


# ---------------------------------------------------------------- membership

def member_status(ctx: Ctx) -> dict[int, dict]:
    """Per learner: batch status (current/alumni/no_batch_recorded), plan labels, cohorts, enrolments."""
    mids = [mid for mid in ctx.members if ctx.is_learner(mid)]
    cms = ctx.s.execute(select(m.CohortMembership, m.Cohort).join(m.Cohort, m.Cohort.id == m.CohortMembership.cohort_id)
                        .where(m.Cohort.community_id == ctx.community.id, m.CohortMembership.observed_at <= ctx.cutoff)).all()
    aps = ctx.s.scalars(select(m.AccessPeriod).join(m.Member).where(m.Member.community_id == ctx.community.id,
                                                                   m.AccessPeriod.observed_at <= ctx.cutoff)).all()
    ens = ctx.s.execute(select(m.CourseEnrolment, m.Course).join(m.Course).where(
        m.Course.community_id == ctx.community.id, m.CourseEnrolment.observed_at <= ctx.cutoff)).all()
    out: dict[int, dict] = {mid: {"current_cohorts": [], "past_cohorts": [], "plans": [], "courses": []} for mid in mids}
    for cm, co in cms:
        if cm.member_id not in out:
            continue
        if _active(cm.valid_from, cm.valid_to, ctx.as_of):
            out[cm.member_id]["current_cohorts"].append(co.key)
        elif cm.valid_from <= ctx.as_of:
            out[cm.member_id]["past_cohorts"].append(co.key)
    for ap in aps:
        if ap.member_id in out and _active(ap.valid_from, ap.valid_to, ctx.as_of) and ap.status == "active":
            out[ap.member_id]["plans"].append(ap.label)
    for en, course in ens:
        if en.member_id in out and _active(en.enrolled_at, en.ended_at, ctx.as_of):
            out[en.member_id]["courses"].append(course.source_course_id)
    for d in out.values():
        d["batch_status"] = "current" if d["current_cohorts"] else ("alumni" if d["past_cohorts"] else "no_batch_recorded")
        d["plans"] = sorted(set(d["plans"])) or ["unknown"]
        for k in ("current_cohorts", "past_cohorts", "courses"):
            d[k] = sorted(set(d[k]))
    return out


def membership_summary(ctx: Ctx, status: dict[int, dict]) -> dict:
    by_batch: dict[str, int] = defaultdict(int)
    by_plan: dict[str, int] = defaultdict(int)
    by_cohort: dict[str, int] = defaultdict(int)
    by_course: dict[str, int] = defaultdict(int)
    for d in status.values():
        by_batch[d["batch_status"]] += 1
        for p in d["plans"]:
            by_plan[p] += 1
        for c in d["current_cohorts"]:
            by_cohort[c] += 1
        for c in d["courses"]:
            by_course[c] += 1
    staff = sum(1 for mm in ctx.members.values() if mm.role in ("staff", "admin"))
    bots = sum(1 for mm in ctx.members.values() if mm.role == "bot")
    return {
        "learners_known": len(status),
        "staff_known": staff,
        "bots_known": bots,
        "by_batch_status": dict(sorted(by_batch.items())),
        "by_plan_label": dict(sorted(by_plan.items())),
        "by_current_cohort": dict(sorted(by_cohort.items())),
        "by_active_course_enrolment": dict(sorted(by_course.items())),
        "note": "Members known to this workspace's records; not necessarily the full Skool member list. "
                "A member may hold several plan labels/cohorts, so breakdowns can sum to more than the total.",
    }


# ---------------------------------------------------------------- participation

def _activity_rows(ctx: Ctx, start: datetime, end: datetime):
    cid = ctx.community.id
    posts = ctx.s.scalars(select(m.Post).where(m.Post.community_id == cid, m.Post.created_at >= start,
                                               m.Post.created_at < end, m.Post.observed_at <= ctx.cutoff)).all()
    comments = ctx.s.scalars(select(m.Comment).where(m.Comment.community_id == cid, m.Comment.created_at >= start,
                                                     m.Comment.created_at < end, m.Comment.observed_at <= ctx.cutoff)).all()
    reactions = ctx.s.scalars(select(m.Reaction).where(m.Reaction.community_id == cid, m.Reaction.created_at >= start,
                                                       m.Reaction.created_at < end, m.Reaction.observed_at <= ctx.cutoff)).all()
    return posts, comments, reactions


def _deleted(obj, cutoff: datetime) -> bool:
    return obj.deleted_confirmed_at is not None and obj.deleted_confirmed_at <= cutoff


def _removed(r: m.Reaction, cutoff: datetime) -> bool:
    return r.removed_confirmed_at is not None and r.removed_confirmed_at <= cutoff


def participation(ctx: Ctx) -> dict:
    posts, comments, reactions = _activity_rows(ctx, ctx.start, ctx.end)
    per: dict[int, dict] = defaultdict(lambda: {"posts": 0, "comments": 0, "likes_given": 0, "likes_received": 0})
    staff_bot = {"posts": 0, "comments": 0, "likes_given": 0}
    cats: dict[str, int] = defaultdict(int)
    deleted = removed = 0
    for p in posts:
        if _deleted(p, ctx.cutoff):
            deleted += 1
            continue
        if ctx.is_learner(p.author_id):
            per[p.author_id]["posts"] += 1
            cats[p.category or "(uncategorised)"] += 1
        else:
            staff_bot["posts"] += 1
    for c in comments:
        if _deleted(c, ctx.cutoff):
            deleted += 1
            continue
        if ctx.is_learner(c.author_id):
            per[c.author_id]["comments"] += 1
        else:
            staff_bot["comments"] += 1
    for r in reactions:
        if _removed(r, ctx.cutoff):
            removed += 1
            continue
        if ctx.is_learner(r.actor_id):
            per[r.actor_id]["likes_given"] += 1
        else:
            staff_bot["likes_given"] += 1
        if ctx.is_learner(r.target_author_id):
            per[r.target_author_id]["likes_received"] += 1
    totals = {k: sum(v[k] for v in per.values()) for k in ("posts", "comments", "likes_given", "likes_received")}
    totals["distinct_contributors"] = sum(1 for v in per.values() if v["posts"] or v["comments"] or v["likes_given"])
    return {
        "totals_learners": totals,
        "staff_and_bot_activity": staff_bot,
        "by_category_posts": dict(sorted(cats.items())),
        "per_member": {str(k): {**v, "member": ctx.ref(k)} for k, v in sorted(per.items())},
        "excluded_confirmed_deleted": deleted,
        "excluded_removed_likes": removed,
        "note": "Likes given and received are separate. Per Skool's documented rule, points come from likes received, "
                "not from giving likes or replying. No observed activity means none observed in this capture, not inactivity.",
    }


def active_days(ctx: Ctx, days: int) -> dict:
    """Distinct Asia/Kolkata calendar days with an observed post, comment or like given, in the window ending at ``end``."""
    start = ctx.end - timedelta(days=days)
    posts, comments, reactions = _activity_rows(ctx, start, ctx.end)
    seen: dict[int, set] = defaultdict(set)
    for p in posts:
        if ctx.is_learner(p.author_id) and not _deleted(p, ctx.cutoff) and p.created_at:
            seen[p.author_id].add(local_date_of(p.created_at))
    for c in comments:
        if ctx.is_learner(c.author_id) and not _deleted(c, ctx.cutoff) and c.created_at:
            seen[c.author_id].add(local_date_of(c.created_at))
    for r in reactions:
        if ctx.is_learner(r.actor_id) and not _removed(r, ctx.cutoff) and r.created_at:
            seen[r.actor_id].add(local_date_of(r.created_at))
    return {
        "window_days": days,
        "members_with_observed_activity": len(seen),
        "per_member_active_days": {str(k): len(v) for k, v in sorted(seen.items())},
        "note": "Observed contribution days only — not time online, visits or study time.",
    }


# ---------------------------------------------------------------- learning

def _entitled(ents: Sequence[m.Entitlement], member_id: int, course_id: int, at: datetime) -> bool:
    return any(e.member_id == member_id and e.course_id == course_id and _active(e.valid_from, e.valid_to, at) for e in ents)


def learning(ctx: Ctx) -> dict:
    cid = ctx.community.id
    courses = {c.id: c for c in ctx.s.scalars(select(m.Course).where(m.Course.community_id == cid)).all()}
    lessons = ctx.s.scalars(select(m.Lesson).where(m.Lesson.course_id.in_(courses.keys()))).all() if courses else []
    lesson_by_id = {lsn.id: lsn for lsn in lessons}
    ents = ctx.s.scalars(select(m.Entitlement).where(m.Entitlement.course_id.in_(courses.keys()),
                                                     m.Entitlement.observed_at <= ctx.cutoff)).all() if courses else []
    enrols = ctx.s.scalars(select(m.CourseEnrolment).where(m.CourseEnrolment.course_id.in_(courses.keys()),
                                                          m.CourseEnrolment.observed_at <= ctx.cutoff)).all() if courses else []
    snaps = ctx.s.scalars(select(m.ProgressSnapshot).where(m.ProgressSnapshot.course_id.in_(courses.keys()),
                                                          m.ProgressSnapshot.observed_at <= ctx.as_of)
                          .order_by(m.ProgressSnapshot.observed_at)).all() if courses else []
    snaps_by: dict[tuple[int, int], list[m.ProgressSnapshot]] = defaultdict(list)
    for sn in snaps:
        snaps_by[(sn.member_id, sn.course_id)].append(sn)

    rows = []
    for en in enrols:
        if not ctx.is_learner(en.member_id) or not _active(en.enrolled_at, en.ended_at, ctx.as_of):
            continue
        course = courses[en.course_id]
        entitled = _entitled(ents, en.member_id, en.course_id, ctx.as_of)
        hist = snaps_by.get((en.member_id, en.course_id), [])
        latest = hist[-1] if hist else None
        baseline = next((h for h in reversed(hist) if h.observed_at < ctx.start), None)
        row: dict[str, Any] = {
            "member": ctx.ref(en.member_id), "course": course.source_course_id, "course_title": course.title,
            "entitled_now": entitled,
        }
        if not entitled:
            row["status"] = "enrolled_without_recorded_access"
        if latest is None or latest.completed_lessons is None:
            row.update(progress="unknown", completed=None, total=None, observed_at=None, change=None,
                       change_status="unknown")
        else:
            row.update(progress="recorded", completed=latest.completed_lessons, total=latest.total_lessons,
                       observed_at=iso(latest.observed_at), source_ref=latest.source_ref)
            if latest.observed_at < ctx.start:
                row["change_status"] = "no_observation_in_interval"
                row["change"] = None
            elif baseline is None:
                row["change_status"] = "no_baseline"
                row["change"] = None
            elif (baseline.lesson_set_hash != latest.lesson_set_hash or baseline.total_lessons != latest.total_lessons
                  or baseline.completed_lessons is None):
                row["change_status"] = "not_comparable"
                row["change"] = None
            else:
                row["change_status"] = "comparable"
                row["change"] = latest.completed_lessons - baseline.completed_lessons
                row["baseline_observed_at"] = iso(baseline.observed_at)
        rows.append(row)

    overdue = _overdue_lessons(ctx, courses, lesson_by_id, ents, snaps_by)
    known = sum(1 for r in rows if r["progress"] == "recorded")
    return {
        "enrolments": rows,
        "enrolments_counted": len(rows),
        "progress_recorded": known,
        "progress_unknown": len(rows) - known,
        "members_with_comparable_progress_increase": len({r["member"]["member_id"] for r in rows
                                                          if r.get("change_status") == "comparable" and r["change"] > 0}),
        "deadline_checks": overdue,
        "note": "Completion markers are recorded completion, not proof of watching, comprehension or mastery. "
                "Changes are shown only between snapshots of the same lesson set.",
    }


def _overdue_lessons(ctx: Ctx, courses, lesson_by_id, ents, snaps_by) -> list[dict]:
    cid = ctx.community.id
    rows = ctx.s.execute(select(m.LessonDeadline, m.Cohort).join(m.Cohort).where(
        m.Cohort.community_id == cid, m.LessonDeadline.due_at < ctx.as_of)).all()
    cms = ctx.s.scalars(select(m.CohortMembership).join(m.Cohort).where(
        m.Cohort.community_id == cid, m.CohortMembership.observed_at <= ctx.cutoff)).all()
    by_cohort: dict[int, list[m.CohortMembership]] = defaultdict(list)
    for cm in cms:
        by_cohort[cm.cohort_id].append(cm)
    grace = timedelta(days=ctx.settings.new_member_grace_days)
    out = []
    for dl, cohort in rows:
        lesson = lesson_by_id.get(dl.lesson_id)
        if lesson is None:
            continue
        course = courses[lesson.course_id]
        for cm in by_cohort.get(cohort.id, []):
            # Deadline applies only to members of this cohort at the due time — alumni of other batches don't inherit it.
            if not ctx.is_learner(cm.member_id) or not _active(cm.valid_from, cm.valid_to, dl.due_at):
                continue
            base = {"member": ctx.ref(cm.member_id), "cohort": cohort.key, "course": course.source_course_id,
                    "lesson": lesson.source_lesson_id, "lesson_title": lesson.title, "due_at": iso(dl.due_at)}
            if lesson.optional:
                continue
            if lesson.released_at is not None and lesson.released_at > dl.due_at:
                continue  # unreleased at due time: never overdue
            if not _entitled(ents, cm.member_id, course.id, dl.due_at):
                out.append({**base, "status": "excluded_no_access"})
                continue
            mem = ctx.members[cm.member_id]
            joined = mem.joined_at or cm.valid_from
            if joined + grace > dl.due_at:
                out.append({**base, "status": "in_grace_period"})
                continue
            hist = snaps_by.get((cm.member_id, course.id), [])
            latest = hist[-1] if hist else None
            if latest is None or latest.completed_lesson_ids is None:
                out.append({**base, "status": "unknown_no_progress_data"})
            elif lesson.source_lesson_id in latest.completed_lesson_ids:
                out.append({**base, "status": "completed_marker_recorded"})
            elif latest.observed_at < dl.due_at:
                out.append({**base, "status": "unknown_stale_progress", "progress_observed_at": iso(latest.observed_at)})
            else:
                out.append({**base, "status": "overdue", "progress_observed_at": iso(latest.observed_at),
                            "source_ref": latest.source_ref})
    return out


# ---------------------------------------------------------------- assignments

def assignments(ctx: Ctx) -> dict:
    cid = ctx.community.id
    subs = ctx.s.execute(select(m.Submission, m.AssignmentDef).outerjoin(m.AssignmentDef)
                         .join(m.Member, m.Member.id == m.Submission.member_id)
                         .where(m.Member.community_id == cid, m.Submission.submitted_at < ctx.as_of,
                                m.Submission.observed_at <= ctx.cutoff)).all()
    fbs = ctx.s.scalars(select(m.Feedback).where(m.Feedback.submission_id.in_([sb.id for sb, _ in subs]),
                                                m.Feedback.observed_at <= ctx.cutoff)).all() if subs else []
    fb_by: dict[int, list[m.Feedback]] = defaultdict(list)
    for f in fbs:
        fb_by[f.submission_id].append(f)
    submitted, delivered, pending, reviewed_not_delivered, ambiguous = [], [], [], [], []
    for sb, a in subs:
        row = {"submission_id": sb.id, "assignment": a.key if a else None, "assignment_title": a.title if a else None,
               "member": ctx.ref(sb.member_id), "submitted_at": iso(sb.submitted_at),
               "due_at": iso(a.due_at) if a and a.due_at else None, "source_ref": sb.source_ref,
               "classification": sb.classification}
        if sb.classification == "ambiguous":
            ambiguous.append(row)
            continue
        if ctx.start <= sb.submitted_at < ctx.end:
            submitted.append(row)
        fl = fb_by.get(sb.id, [])
        dlv = [f for f in fl if f.feedback_delivered_at and f.feedback_delivered_at < ctx.as_of]
        for f in dlv:
            assert f.feedback_delivered_at is not None
            if ctx.start <= f.feedback_delivered_at < ctx.end:
                delivered.append({**row, "reviewer": ctx.ref(f.reviewer_id), "feedback_delivered_at": iso(f.feedback_delivered_at),
                                  "channel": f.feedback_channel, "assessment_result": f.assessment_result,
                                  "follow_up": f.follow_up})
        if not dlv:
            rev = [f for f in fl if f.reviewed_at and f.reviewed_at < ctx.as_of]
            age_h = round((ctx.as_of - sb.submitted_at).total_seconds() / 3600, 1)
            if rev:
                reviewed_not_delivered.append({**row, "reviewer": ctx.ref(rev[-1].reviewer_id), "age_hours": age_h})
            else:
                pending.append({**row, "age_hours": age_h})
    return {
        "submitted_in_interval": submitted,
        "feedback_delivered_in_interval": delivered,
        "awaiting_review": sorted(pending, key=lambda r: -r["age_hours"]),
        "reviewed_feedback_not_delivered": reviewed_not_delivered,
        "ambiguous_classification_needs_review": ambiguous,
        "note": "Submission, review, feedback delivery and assessment result are separate facts. "
                "Submissions come from configured category mappings or manual labels — never guessed from arbitrary posts.",
    }


# ---------------------------------------------------------------- wins

def wins(ctx: Ctx) -> dict:
    rows = ctx.s.execute(select(m.Win, m.Post).join(m.Post, m.Post.id == m.Win.post_id).where(
        m.Post.community_id == ctx.community.id, m.Win.recorded_at >= ctx.start, m.Win.recorded_at < ctx.end,
        m.Win.observed_at <= ctx.cutoff)).all()
    return {"wins": [{"member": ctx.ref(w.member_id), "category": w.category, "verification": w.verification,
                      "title": p.title, "recorded_at": iso(w.recorded_at), "source_ref": p.source_ref,
                      "source_post_id": p.source_post_id} for w, p in rows],
            "note": "Member-reported wins remain self-reported unless independently verified."}


# ---------------------------------------------------------------- support

def _elapsed_hours(ctx: Ctx, a: datetime, b: datetime) -> float:
    st = ctx.settings
    if st.support_target_basis == "working":
        return working_hours_between(a, b, st.working_hours_start, st.working_hours_end)
    return (b - a).total_seconds() / 3600


def question_state(ctx: Ctx, q: m.SupportQuestion, events: list[m.SupportEvent]) -> dict:
    evs = sorted([e for e in events if e.at < ctx.as_of and e.observed_at <= ctx.cutoff], key=lambda e: e.at)
    staff_resp = [e for e in evs if e.kind == "staff_response"]
    peer = [e for e in evs if e.kind == "peer_response"]
    bot = [e for e in evs if e.kind == "bot_response"]
    reopen_times = [e.at for e in evs if e.kind == "reopened"]
    last_reopen = max(reopen_times) if reopen_times else None
    resolved = [e for e in evs if e.kind in ("resolution_confirmed", "closed") and (last_reopen is None or e.at > last_reopen)]
    clar = [e for e in evs if e.kind == "clarification_request" and (last_reopen is None or e.at > last_reopen)]
    member_replies = [e for e in evs if e.kind == "member_reply"]
    assigned = [e for e in evs if e.kind == "assigned"]
    if resolved:
        state = "resolved"
    elif clar and not any(r.at > clar[-1].at for r in member_replies):
        state = "awaiting_member"
    else:
        state = "awaiting_staff"
    first_staff = staff_resp[0].at if staff_resp else None
    target = ctx.settings.support_first_response_target_hours
    if first_staff:
        frt = _elapsed_hours(ctx, q.asked_at, first_staff)
        breach = frt > target
    else:
        frt = None
        breach = _elapsed_hours(ctx, q.asked_at, ctx.as_of) > target
    owner = assigned[-1].actor_id if assigned else q.assigned_to_id
    return {
        "question_id": q.id, "source_question_id": q.source_question_id, "member": ctx.ref(q.member_id),
        "asked_at": iso(q.asked_at), "text": q.text, "source_ref": q.source_ref,
        "state_from_evidence": state, "stored_workflow_state": q.state,
        "first_staff_response_at": iso(first_staff),
        "first_staff_response_hours": None if frt is None else round(frt, 2),
        "peer_responses": len(peer), "bot_responses": len(bot),
        "first_peer_response_at": iso(peer[0].at) if peer else None,
        "first_bot_response_at": iso(bot[0].at) if bot else None,
        "clarification_requests": len(clar), "reopened_count": len(reopen_times),
        "resolution_evidence": [{"kind": e.kind, "at": iso(e.at), "by": ctx.ref(e.actor_id), "note": e.note} for e in resolved],
        "assigned_owner": ctx.ref(owner),
        "first_response_target_breached": breach,
        "age_hours": round((ctx.as_of - q.asked_at).total_seconds() / 3600, 1),
    }


def support(ctx: Ctx) -> dict:
    qs = ctx.s.scalars(select(m.SupportQuestion).where(m.SupportQuestion.community_id == ctx.community.id,
                                                       m.SupportQuestion.asked_at < ctx.as_of,
                                                       m.SupportQuestion.observed_at <= ctx.cutoff)).all()
    evs = ctx.s.scalars(select(m.SupportEvent).where(m.SupportEvent.question_id.in_([q.id for q in qs]))).all() if qs else []
    ev_by: dict[int, list] = defaultdict(list)
    for e in evs:
        ev_by[e.question_id].append(e)
    states = [question_state(ctx, q, ev_by[q.id]) for q in qs]
    new = [s for s, q in zip(states, qs, strict=True) if ctx.start <= q.asked_at < ctx.end]
    unresolved = [s for s in states if s["state_from_evidence"] != "resolved"]
    frts = sorted(s["first_staff_response_hours"] for s in new if s["first_staff_response_hours"] is not None)
    return {
        "target": {"first_staff_response_hours": ctx.settings.support_first_response_target_hours,
                   "basis": ctx.settings.support_target_basis,
                   "note": "Demonstration target, not a Social Eagle commitment."},
        "new_in_interval": new,
        "new_count": len(new),
        "new_with_staff_response": sum(1 for s in new if s["first_staff_response_at"]),
        "median_first_staff_response_hours_new": frts[len(frts) // 2] if frts else None,
        "unresolved": sorted(unresolved, key=lambda s: -s["age_hours"]),
        "unresolved_awaiting_staff": sum(1 for s in unresolved if s["state_from_evidence"] == "awaiting_staff"),
        "unresolved_awaiting_member": sum(1 for s in unresolved if s["state_from_evidence"] == "awaiting_member"),
        "target_breaches_open": [s for s in unresolved if s["first_response_target_breached"] and not s["first_staff_response_at"]],
        "note": "Staff, peer and bot responses are measured separately. A reply or acknowledgement is not resolution; "
                "only resolution_confirmed/closed evidence counts.",
    }


# ---------------------------------------------------------------- leaderboard

def leaderboard(ctx: Ctx) -> dict:
    out = {}
    for period in ("7d", "30d", "all"):
        snaps = ctx.s.scalars(select(m.LeaderboardSnapshot).where(
            m.LeaderboardSnapshot.community_id == ctx.community.id, m.LeaderboardSnapshot.period == period,
            m.LeaderboardSnapshot.observed_at <= ctx.as_of).order_by(m.LeaderboardSnapshot.observed_at)).all()
        if not snaps:
            continue
        latest = snaps[-1]
        prev = snaps[-2] if len(snaps) > 1 else None
        entries = [{"member": ctx.ref(e.member_id), "rank": e.rank, "points": e.points} for e in latest.entries]
        changes = None
        comparability = "no_previous_snapshot"
        if prev is not None:
            prev_map = {e.member_id: e for e in prev.entries}
            changes = []
            for e in latest.entries:
                pe = prev_map.get(e.member_id)
                if pe and pe.points is not None and e.points is not None:
                    changes.append({"member": ctx.ref(e.member_id), "points_change": e.points - pe.points,
                                    "rank_change": (pe.rank - e.rank) if pe.rank and e.rank else None})
            comparability = "complete_snapshots" if (latest.is_complete and prev.is_complete) else \
                "partial_snapshots_members_in_both_only"
        out[period] = {"observed_at": iso(latest.observed_at), "is_complete": latest.is_complete, "entries": entries,
                       "previous_observed_at": iso(prev.observed_at) if prev else None, "changes": changes,
                       "comparability": comparability}
    return {"periods": out, "note": "Directly observed points/ranks. A partial snapshot is not the official full leaderboard; "
                                    "points do not establish learning or helpfulness."}


# ---------------------------------------------------------------- outreach & follow-up

def outreach_and_followups(ctx: Ctx, status: dict, learn: dict, supp: dict, assign: dict, health: dict) -> dict:
    grace = timedelta(days=ctx.settings.new_member_grace_days)
    reasons: dict[int, list[str]] = defaultdict(list)
    for row in learn["deadline_checks"]:
        if row["status"] == "overdue":
            reasons[row["member"]["member_id"]].append(
                f"Lesson '{row['lesson_title']}' ({row['cohort']}) due {row['due_at']} has no completion marker "
                f"as of progress observed {row['progress_observed_at']}.")
    for q in supp["unresolved"]:
        if q["state_from_evidence"] == "awaiting_staff" and q["first_response_target_breached"]:
            reasons[q["member"]["member_id"]].append(
                f"Question asked {q['asked_at']} has no staff response within the target ({q['age_hours']} h old).")
    # Quiet-and-not-progressing rule only when coverage is complete for the full lookback window.
    n = ctx.settings.outreach_quiet_days
    quiet_window_note = None
    disc_ok = health.get("discussions", {}).get("state") == "ok"
    if disc_ok:
        win_ctx = Ctx(ctx.s, ctx.community, ctx.end - timedelta(days=n), ctx.end, ctx.cutoff, ctx.settings, ctx.members)
        cov = source_health(win_ctx)
        if cov.get("discussions", {}).get("state") == "ok":
            ad = active_days(ctx, n)["per_member_active_days"]
            progressed = {r["member"]["member_id"] for r in learn["enrolments"]
                          if r.get("observed_at") and r.get("completed") and r["observed_at"] >= iso(ctx.end - timedelta(days=n))
                          and r.get("change_status") == "comparable" and (r.get("change") or 0) > 0}
            for mid, st in status.items():
                mem = ctx.members[mid]
                if st["batch_status"] != "current" or (mem.joined_at and mem.joined_at + grace > ctx.as_of):
                    continue
                if str(mid) not in ad and mid not in progressed:
                    has_progress = any(r["member"]["member_id"] == mid and r["progress"] == "recorded"
                                       for r in learn["enrolments"])
                    tail = "no recorded progress increase" if has_progress else "progress data unknown"
                    reasons[mid].append(f"Current-batch member: no observed posts/comments/likes and {tail} "
                                        f"in the last {n} days (discussion coverage complete for this window).")
        else:
            quiet_window_note = f"Quiet-member rule skipped: discussion coverage incomplete for the last {n} days."
    else:
        quiet_window_note = "Quiet-member rule skipped: discussion source not fully covered for this interval."
    outreach = [{"member": ctx.ref(mid), "reasons": rs} for mid, rs in sorted(reasons.items())]

    follow = []
    for a in assign["awaiting_review"]:
        follow.append({"owner": None, "reason": f"Assignment '{a['assignment_title']}' awaiting review for {a['age_hours']} h",
                       "member": a["member"], "source_ref": a["source_ref"]})
    for a in assign["reviewed_feedback_not_delivered"]:
        follow.append({"owner": a["reviewer"], "reason": "Reviewed but feedback delivery not recorded",
                       "member": a["member"], "source_ref": a["source_ref"]})
    for a in assign["ambiguous_classification_needs_review"]:
        follow.append({"owner": None, "reason": "Possible submission needs manual classification",
                       "member": a["member"], "source_ref": a["source_ref"]})
    for q in supp["unresolved"]:
        if q["state_from_evidence"] == "awaiting_staff":
            follow.append({"owner": q["assigned_owner"], "reason": f"Unresolved question awaiting staff ({q['age_hours']} h)"
                           + (" — response target breached" if q["first_response_target_breached"] else ""),
                           "member": q["member"], "source_ref": q["source_ref"]})
    return {"outreach_candidates": outreach, "staff_follow_ups": follow, "quiet_rule_note": quiet_window_note,
            "note": "Transparent rule-based reasons only; no risk or blame score. Low points alone never trigger outreach."}

