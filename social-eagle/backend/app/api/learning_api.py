from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..models import (
    Assignment,
    Course,
    Event,
    EventAttendance,
    EventRegistration,
    Lesson,
    LessonCompletion,
    Member,
    ProgressEvent,
    Submission,
)
from ..security import require_admin
from ..services import metrics
from ..timeutil import iso, local_date
from .deps import build_scope, scope_params

router = APIRouter(prefix="/api", tags=["learning"], dependencies=[Depends(require_admin)])


@router.get("/learning/courses")
def courses(sp: dict = Depends(scope_params), db: Session = Depends(get_db)) -> dict:
    scope = build_scope(db, sp)
    return {**metrics.learning(db, scope), "scope": scope.describe(), "coverage": metrics.coverage(db, scope),
            "provenance": "Local simulator (SYNTHETIC). Access tiers are synthetic evaluation rules, not Social Eagle policy."}


@router.get("/learning/courses/{course_id}")
def course_detail(course_id: int, db: Session = Depends(get_db)) -> dict:
    c = db.get(Course, course_id)
    if c is None:
        raise HTTPException(404, "course not found")
    lessons = db.execute(select(Lesson).where(Lesson.course_id == c.id).order_by(Lesson.position)).scalars().all()
    rows = []
    for lsn in lessons:
        done = db.execute(select(func.count()).where(LessonCompletion.lesson_id == lsn.id, LessonCompletion.completed.is_(True))).scalar()
        rows.append({"id": lsn.id, "upstream_id": lsn.upstream_id, "position": lsn.position, "title": lsn.title,
                     "module": lsn.module, "video_minutes": lsn.video_minutes, "members_marked_complete": done})
    asg = []
    for a in db.execute(select(Assignment).where(Assignment.course_id == c.id)).scalars():
        by = dict(db.execute(select(Submission.status, func.count()).where(Submission.assignment_id == a.id)
                             .group_by(Submission.status)).all())
        asg.append({"id": a.id, "title": a.title, "submissions": by,
                    "awaiting_review": by.get("submitted", 0)})
    since = clock.now() - timedelta(days=14)
    recent = db.execute(select(ProgressEvent, Member, Lesson).join(Member, Member.id == ProgressEvent.member_id)
                        .join(Lesson, Lesson.id == ProgressEvent.lesson_id)
                        .where(Lesson.course_id == c.id, ProgressEvent.occurred_at >= since)
                        .order_by(ProgressEvent.occurred_at.desc()).limit(30)).all()
    return {"course": {"id": c.id, "title": c.title, "description": c.description, "access_tiers": c.access_tiers,
                       "policy_label": c.policy_label}, "lessons": rows, "assignments": asg,
            "recent_progress": [{"member_id": m.id, "member": m.display_name, "lesson": lsn.title, "kind": pe.kind,
                                 "at": iso(pe.occurred_at)} for pe, m, lsn in recent],
            "note": "Marked complete is a member action; it does not prove the video was watched or understood. "
                    "Assignments, submissions and reviewer feedback are tracked separately."}


@router.get("/learning/stalled")
def stalled(days: int = Query(14, ge=1, le=180), limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)) -> dict:
    gid = metrics.main_group_id(db)
    ids = metrics.segment_members(db, "stalled_progress", {"days": days}, gid)
    out = []
    for mid in ids[:limit]:
        m = db.get(Member, mid)
        last = db.execute(select(func.max(ProgressEvent.occurred_at)).where(ProgressEvent.member_id == mid)).scalar()
        out.append({"member_id": mid, "name": m.display_name if m else None, "tier": m.tier if m else None,
                    "last_progress": iso(last), "next_lesson": metrics.next_lesson(db, mid)})
    return {"rule": f"Has marked-complete lessons, none in the last {days} days, accessible lessons remaining.",
            "total": len(ids), "rows": out}


@router.get("/events")
def events(past_days: int = Query(60, ge=1, le=365), future_days: int = Query(30, ge=0, le=365), db: Session = Depends(get_db)) -> dict:
    gid = metrics.main_group_id(db)
    today = local_date(clock.now())
    scope = metrics.Scope(group_id=gid, start=today - timedelta(days=past_days), end=today + timedelta(days=future_days))
    return {**metrics.events_metrics(db, scope), "scope": scope.describe()}


@router.get("/events/{event_id}")
def event_detail(event_id: int, db: Session = Depends(get_db)) -> dict:
    ev = db.get(Event, event_id)
    if ev is None:
        raise HTTPException(404, "event not found")
    regs = {r.member_id: r for r in db.execute(select(EventRegistration).where(EventRegistration.event_id == ev.id)).scalars()}
    att = {a.member_id: a for a in db.execute(select(EventAttendance).where(EventAttendance.event_id == ev.id)).scalars()}
    rows = []
    for mid in sorted(set(regs) | set(att)):
        m = db.get(Member, mid)
        a = att.get(mid)
        rows.append({"member_id": mid, "name": m.display_name if m else None, "registered": mid in regs,
                     "registered_at": iso(regs[mid].registered_at) if mid in regs else None, "attended": a is not None,
                     "duration_minutes": a.duration_minutes if a else None,
                     "duration_status": ("known" if a and a.duration_minutes is not None else "unknown" if a else "n/a")})
    return {"event": {"id": ev.id, "title": ev.title, "starts_at": iso(ev.starts_at), "ends_at": iso(ev.ends_at),
                      "cancelled": ev.cancelled, "upcoming": ev.starts_at > clock.now()}, "people": rows}


@router.get("/engagement")
def engagement(sp: dict = Depends(scope_params), db: Session = Depends(get_db)) -> dict:
    scope = build_scope(db, sp)
    days = (scope.end - scope.start).days + 1
    prev = metrics.Scope(group_id=scope.group_id, start=scope.start - timedelta(days=days), end=scope.start - timedelta(days=1),
                         datasets=scope.datasets, include_staff=scope.include_staff, include_bot=scope.include_bot)
    return {"scope": scope.describe(), "contributions": metrics.contributions(db, scope),
            "comparison": metrics.compare(db, prev, scope), "leaderboard": metrics.leaderboard(db, scope, top=15),
            "coverage": metrics.coverage(db, scope), "definitions": metrics.DEFINITIONS}


@router.get("/learning/time-spent/{member_id}")
def time_spent(member_id: int, sp: dict = Depends(scope_params), db: Session = Depends(get_db)) -> dict:
    if db.get(Member, member_id) is None:
        raise HTTPException(404, "member not found")
    s, e = build_scope(db, sp).utc
    return metrics.time_spent(db, member_id, s, e)
