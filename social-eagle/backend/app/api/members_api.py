from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..models import (
    Action,
    Course,
    Event,
    EventAttendance,
    EventRegistration,
    Lesson,
    LessonCompletion,
    Member,
    MemberNote,
    MemberTag,
    Post,
    ProgressEvent,
    Reaction,
    Segment,
    Submission,
    SupportItem,
)
from ..security import require_admin
from ..services import metrics, notify
from ..timeutil import iso
from .deps import build_scope, scope_params

router = APIRouter(prefix="/api", tags=["members"], dependencies=[Depends(require_admin)])

SORTS = {"name": Member.display_name, "joined": Member.joined_at, "observed": Member.observed_at}


def member_row(m: Member, last: object | None = None) -> dict:
    return {"id": m.id, "upstream_id": m.upstream_id, "display_name": m.display_name, "role": m.role, "tier": m.tier,
            "status": m.status, "joined_at": iso(m.joined_at), "left_at": iso(m.left_at), "is_staff": m.is_staff,
            "is_bot": m.is_bot, "onboarding_status": m.onboarding_status, "rejoin_count": m.rejoin_count,
            "tags": sorted(t.tag for t in m.tags), "dataset": m.dataset, "data_freshness": iso(m.observed_at),
            "last_observed_contribution": iso(last) if last else None}  # type: ignore[arg-type]


@router.get("/members")
def list_members(
    q: str | None = Query(None, max_length=100),
    tier: str | None = None,
    status: str | None = None,
    role: str | None = None,
    tag: str | None = None,
    segment_id: int | None = None,
    group_id: int | None = None,
    sort: str = Query("name", pattern="^(name|joined|observed|last_contribution)$"),
    desc: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    gid = group_id or metrics.main_group_id(db)
    last_post = select(Post.author_id.label("mid"), func.max(Post.created_at).label("t")).group_by(Post.author_id).subquery()
    last_rx = select(Reaction.member_id.label("mid"), func.max(Reaction.created_at).label("t")).group_by(Reaction.member_id).subquery()
    last_expr = func.max(func.coalesce(last_post.c.t, "0"), func.coalesce(last_rx.c.t, "0"))
    qy = (select(Member, last_post.c.t, last_rx.c.t).outerjoin(last_post, last_post.c.mid == Member.id)
          .outerjoin(last_rx, last_rx.c.mid == Member.id).where(Member.group_id == gid))
    if q:
        like = f"%{q}%"
        qy = qy.where(or_(Member.display_name.ilike(like), Member.upstream_id.ilike(like), Member.email.ilike(like)))
    if tier:
        qy = qy.where(Member.tier == tier)
    if status:
        qy = qy.where(Member.status == status)
    if role:
        qy = qy.where(Member.role == role)
    if tag:
        qy = qy.where(Member.id.in_(select(MemberTag.member_id).where(MemberTag.tag == tag)))
    seg_info = None
    if segment_id:
        seg = db.get(Segment, segment_id)
        if seg is None:
            raise HTTPException(404, "segment not found")
        ids = metrics.segment_members(db, seg.rule, seg.params, gid)
        qy = qy.where(Member.id.in_(ids))
        seg_info = {"id": seg.id, "name": seg.name, "rule": seg.rule, "params": seg.params, "description": seg.description}
    total = db.execute(select(func.count()).select_from(qy.subquery())).scalar()
    order = last_expr if sort == "last_contribution" else SORTS[sort]
    qy = qy.order_by(order.desc() if desc else order.asc(), Member.id).offset((page - 1) * page_size).limit(page_size)
    rows = []
    for m, lp, lr in db.execute(qy).all():
        last = max([t for t in (lp, lr) if t], default=None)
        rows.append(member_row(m, last))
    return {"total": total, "page": page, "page_size": page_size, "rows": rows, "segment": seg_info,
            "note": "Last observed contribution = latest post/comment/reaction seen. No contribution ≠ no visits or learning."}


@router.get("/members/{member_id}")
def member_detail(member_id: int, sp: dict = Depends(scope_params), db: Session = Depends(get_db)) -> dict:
    m = db.get(Member, member_id)
    if m is None:
        raise HTTPException(404, "member not found")
    sp = {**sp, "group_id": m.group_id, "days": max(sp["days"], 90) if not sp["start"] else sp["days"]}
    scope = build_scope(db, sp)
    profile = metrics.member_profile(db, m.id, scope)
    activity = []
    for p in db.execute(select(Post).where(Post.author_id == m.id).order_by(Post.created_at.desc()).limit(40)).scalars():
        activity.append({"type": p.kind, "at": iso(p.created_at), "title": p.title, "excerpt": p.body[:160],
                         "link": f"/discussions/{p.root_id or p.id}", "deleted": p.deleted_at is not None,
                         "edited": p.edited_at is not None, "source": "observed"})
    for r, p in db.execute(select(Reaction, Post).join(Post, Post.id == Reaction.post_id).where(Reaction.member_id == m.id)
                           .order_by(Reaction.created_at.desc()).limit(20)).all():
        activity.append({"type": "reaction", "at": iso(r.created_at), "title": f"Liked: {p.title or p.body[:50]}",
                         "link": f"/discussions/{p.root_id or p.id}", "source": "observed"})
    for pe, lsn, c in db.execute(select(ProgressEvent, Lesson, Course).join(Lesson, Lesson.id == ProgressEvent.lesson_id)
                                 .join(Course, Course.id == Lesson.course_id).where(ProgressEvent.member_id == m.id)
                                 .order_by(ProgressEvent.occurred_at.desc()).limit(40)).all():
        activity.append({"type": f"lesson_{pe.kind}", "at": iso(pe.occurred_at), "title": f"{c.title} — {lsn.title}",
                         "link": f"/learning?course={c.id}", "source": "observed (marked complete; not proof of viewing)"})
    for a, ev in db.execute(select(EventAttendance, Event).join(Event, Event.id == EventAttendance.event_id)
                            .where(EventAttendance.member_id == m.id).order_by(Event.starts_at.desc()).limit(20)).all():
        dur = f"{a.duration_minutes:.0f} min" if a.duration_minutes is not None else "duration unknown"
        activity.append({"type": "event_attended", "at": iso(a.joined_at or ev.starts_at), "title": f"{ev.title} ({dur})",
                         "link": f"/events/{ev.id}", "source": "observed"})
    activity.sort(key=lambda x: x["at"] or "", reverse=True)
    progress = []
    for c in db.execute(select(Course).where(Course.group_id == m.group_id).order_by(Course.id)).scalars():
        lessons = db.execute(select(Lesson).where(Lesson.course_id == c.id).order_by(Lesson.position)).scalars().all()
        done = {lc.lesson_id: lc for lc in db.execute(select(LessonCompletion).where(
            LessonCompletion.member_id == m.id, LessonCompletion.lesson_id.in_([lsn.id for lsn in lessons]))).scalars()}
        accessible = (m.tier or "") in c.tiers()
        progress.append({"course_id": c.id, "title": c.title, "accessible": accessible, "access_tiers": c.access_tiers,
                         "lessons": len(lessons), "marked_complete": sum(1 for v in done.values() if v.completed),
                         "lesson_states": [{"title": lsn.title, "completed": bool(done.get(lsn.id) and done[lsn.id].completed),
                                            "at": iso(done[lsn.id].completed_at) if lsn.id in done else None} for lsn in lessons]})
    subs = [{"assignment": s.assignment_id, "status": s.status, "submitted_at": iso(s.submitted_at), "reviewed_at": iso(s.reviewed_at),
             "feedback": s.feedback} for s in db.execute(select(Submission).where(Submission.member_id == m.id)).scalars()]
    support = [{"id": i.id, "status": i.status, "label": i.label, "label_source": i.label_source, "title": p.title,
                "link": f"/discussions/{p.id}", "created_at": iso(p.created_at)} for i, p in db.execute(
        select(SupportItem, Post).join(Post, Post.id == SupportItem.post_id).where(Post.author_id == m.id)
        .order_by(Post.created_at.desc())).all()]
    follow = [{"id": a.id, "kind": a.kind, "state": a.state, "created_at": iso(a.created_at), "origin": a.origin,
               "simulated": a.simulated} for a in db.execute(select(Action).where(
                   or_(Action.member_id == m.id, and_(Action.target_type == "member", Action.target_upstream_id == m.upstream_id)))
                   .order_by(Action.created_at.desc())).scalars()]
    notes = [{"id": n.id, "body": n.body, "author": n.author, "created_at": iso(n.created_at)} for n in db.execute(
        select(MemberNote).where(MemberNote.member_id == m.id).order_by(MemberNote.created_at.desc())).scalars()]
    regs = db.execute(select(func.count()).where(EventRegistration.member_id == m.id)).scalar()
    same_name = db.execute(select(func.count()).where(Member.group_id == m.group_id, Member.display_name == m.display_name,
                                                      Member.id != m.id)).scalar()
    return {"member": member_row(m), "profile": profile, "scope": scope.describe(), "activity": activity[:80],
            "progress": progress, "submissions": subs, "support_items": support, "follow_ups": follow, "notes": notes,
            "events_registered": regs, "next_lesson": metrics.next_lesson(db, m.id),
            "identity_note": f"{same_name} other member(s) share this display name; identity is the upstream ID." if same_name else None}


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


@router.post("/members/{member_id}/notes")
def add_note(member_id: int, body: NoteIn, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    if db.get(Member, member_id) is None:
        raise HTTPException(404, "member not found")
    n = MemberNote(member_id=member_id, body=body.body, author=user.username, created_at=clock.now())
    db.add(n)
    notify.audit(db, user.username, "member.note_added", member_id=member_id)
    db.commit()
    return {"id": n.id, "body": n.body, "author": n.author, "created_at": iso(n.created_at)}


@router.delete("/members/{member_id}/notes/{note_id}")
def delete_note(member_id: int, note_id: int, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    n = db.get(MemberNote, note_id)
    if n is None or n.member_id != member_id:
        raise HTTPException(404, "note not found")
    db.delete(n)
    db.commit()
    return {"ok": True}


class TagIn(BaseModel):
    tag: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9 _-]+$")


@router.post("/members/{member_id}/tags")
def add_tag(member_id: int, body: TagIn, db: Session = Depends(get_db)) -> dict:
    m = db.get(Member, member_id)
    if m is None:
        raise HTTPException(404, "member not found")
    if body.tag not in {t.tag for t in m.tags}:
        m.tags.append(MemberTag(tag=body.tag))
    db.commit()
    return {"tags": sorted(t.tag for t in m.tags)}


@router.delete("/members/{member_id}/tags/{tag}")
def remove_tag(member_id: int, tag: str, db: Session = Depends(get_db)) -> dict:
    m = db.get(Member, member_id)
    if m is None:
        raise HTTPException(404, "member not found")
    if tag.startswith("source:"):
        raise HTTPException(400, "Source tags come from the community source and cannot be removed here")
    for t in list(m.tags):
        if t.tag == tag:
            m.tags.remove(t)
    db.commit()
    return {"tags": sorted(t.tag for t in m.tags)}


@router.get("/segments")
def segments(db: Session = Depends(get_db)) -> list[dict]:
    gid = metrics.main_group_id(db)
    return [{"id": s.id, "name": s.name, "rule": s.rule, "params": s.params, "description": s.description, "builtin": s.builtin,
             "count": len(metrics.segment_members(db, s.rule, s.params, gid))}
            for s in db.execute(select(Segment).order_by(Segment.id)).scalars()]


class SegmentParamsIn(BaseModel):
    params: dict[str, int]


@router.put("/segments/{segment_id}")
def update_segment(segment_id: int, body: SegmentParamsIn, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    s = db.get(Segment, segment_id)
    if s is None:
        raise HTTPException(404, "segment not found")
    for k, v in body.params.items():
        if k not in ("days", "hours") or not 1 <= v <= 365:
            raise HTTPException(400, "params must be days/hours between 1 and 365")
    s.params = {**s.params, **body.params}
    notify.audit(db, user.username, "segment.update", segment=s.name, params=s.params)
    db.commit()
    return {"id": s.id, "params": s.params, "count": len(metrics.segment_members(db, s.rule, s.params, metrics.main_group_id(db)))}
