"""Evaluation lab: inject events into the local simulator. Exists only in evaluation mode (enforced here)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..connectors.factory import get_adapter, get_store
from ..connectors.simulator import FAULT_KINDS
from ..db import get_db
from ..models import Event, Lesson, Post
from ..security import require_admin
from ..services import jobs, notify, sync
from ..timeutil import iso


def evaluation_only() -> None:
    if get_settings().run_mode != "evaluation":
        raise HTTPException(404, "The evaluation lab does not exist outside evaluation mode")


router = APIRouter(prefix="/api/lab", tags=["lab"], dependencies=[Depends(evaluation_only), Depends(require_admin)])
ID = r"^[A-Za-z0-9_.:-]+$"


def _done(db: Session, user: object, what: str, rec: dict, auto_sync: bool) -> dict:
    notify.audit(db, getattr(user, "username", "?"), f"lab.{what}", upstream_id=rec.get("upstream_id"))
    db.commit()
    out = {"simulator_record": rec, "simulated": True}
    if auto_sync:
        out["sync"] = sync_now_impl(db)
    return out


def sync_now_impl(db: Session) -> dict:
    res = sync.sync_once(db, get_adapter("simulator"))
    for pid in res.pop("new_posts", []) if res.get("ok") else []:
        jobs.enqueue(db, "evaluate_post", f"evaluate_post:{pid}", {"post_id": pid}, priority=4)
    db.commit()
    return res


@router.get("/state")
def state() -> dict:
    st = get_store()
    return {"counts": st.counts(), "faults": st.faults(), "fault_kinds": FAULT_KINDS, "write_log": st.write_log(30),
            "seed": st.meta("seed"), "anchor": st.meta("anchor"),
            "note": "SYNTHETIC local community. Every write here stays on this computer."}


@router.get("/catalog")
def catalog(db: Session = Depends(get_db)) -> dict:
    lessons = db.execute(select(Lesson).order_by(Lesson.course_id, Lesson.position)).scalars().all()
    events = db.execute(select(Event).order_by(Event.starts_at.desc()).limit(25)).scalars().all()
    posts = db.execute(select(Post).where(Post.kind == "post").order_by(Post.created_at.desc()).limit(25)).scalars().all()
    return {"lessons": [{"upstream_id": x.upstream_id, "title": x.title} for x in lessons],
            "events": [{"upstream_id": e.upstream_id, "title": e.title, "starts_at": iso(e.starts_at)} for e in events],
            "posts": [{"upstream_id": p.upstream_id, "title": p.title} for p in posts]}


class QuestionIn(BaseModel):
    member_upstream_id: str = Field(pattern=ID, max_length=120)
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=3, max_length=3000)
    category: str = Field("Questions", max_length=60)
    auto_sync: bool = True


@router.post("/question")
def add_question(body: QuestionIn, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    try:
        rec = get_store().add_post(author_id=body.member_upstream_id, title=body.title, body=body.body, category=body.category)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _done(db, user, "question", rec, body.auto_sync)


class CommentIn(BaseModel):
    post_upstream_id: str = Field(pattern=ID, max_length=120)
    member_upstream_id: str = Field(pattern=ID, max_length=120)
    body: str = Field(min_length=1, max_length=3000)
    auto_sync: bool = True


@router.post("/comment")
def add_comment(body: CommentIn, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    try:
        rec = get_store().add_post(author_id=body.member_upstream_id, body=body.body, parent_id=body.post_upstream_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _done(db, user, "comment", rec, body.auto_sync)


class ProgressIn(BaseModel):
    member_upstream_id: str = Field(pattern=ID, max_length=120)
    lesson_upstream_id: str = Field(pattern=ID, max_length=120)
    completed: bool = True
    auto_sync: bool = True


@router.post("/progress")
def change_progress(body: ProgressIn, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    try:
        rec = get_store().set_progress(member_id=body.member_upstream_id, lesson_id=body.lesson_upstream_id, completed=body.completed)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _done(db, user, "progress", rec, body.auto_sync)


class ReactionIn(BaseModel):
    post_upstream_id: str = Field(pattern=ID, max_length=120)
    member_upstream_id: str = Field(pattern=ID, max_length=120)
    auto_sync: bool = True


@router.post("/reaction")
def add_reaction(body: ReactionIn, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    try:
        rec = get_store().add_reaction(post_id=body.post_upstream_id, member_id=body.member_upstream_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _done(db, user, "reaction", rec, body.auto_sync)


class JoinIn(BaseModel):
    event_upstream_id: str = Field(pattern=ID, max_length=120)
    member_upstream_id: str = Field(pattern=ID, max_length=120)
    attend: bool = False
    minutes: float | None = Field(None, ge=0, le=600)
    auto_sync: bool = True


@router.post("/event-join")
def join_event(body: JoinIn, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    try:
        rec = get_store().join_event(event_id=body.event_upstream_id, member_id=body.member_upstream_id, attend=body.attend,
                                     minutes=body.minutes)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _done(db, user, "event_join", {"upstream_id": body.event_upstream_id, **rec}, body.auto_sync)


class MemberIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=120)
    tier: str = Field("general", pattern="^(general|annual)$")
    auto_sync: bool = True


@router.post("/member")
def add_member(body: MemberIn, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    return _done(db, user, "member", get_store().add_member(display_name=body.display_name, tier=body.tier), body.auto_sync)


class EditIn(BaseModel):
    post_upstream_id: str = Field(pattern=ID, max_length=120)
    body: str | None = Field(None, max_length=3000)
    delete: bool = False
    auto_sync: bool = True


@router.post("/edit-post")
def edit_post(body: EditIn, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    try:
        st = get_store()
        rec = st.delete_post(body.post_upstream_id) if body.delete else st.edit_post(body.post_upstream_id, body.body or "")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _done(db, user, "edit_post", rec, body.auto_sync)


class FaultIn(BaseModel):
    kind: str
    remaining: int = Field(-1, ge=-1, le=100)
    params: dict = Field(default_factory=dict)


@router.post("/fault")
def set_fault(body: FaultIn, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    if body.kind not in FAULT_KINDS:
        raise HTTPException(400, f"unknown fault; choose from {sorted(FAULT_KINDS)}")
    get_store().set_fault(body.kind, body.remaining, body.params)
    notify.audit(db, user.username, "lab.fault", kind=body.kind, remaining=body.remaining)
    db.commit()
    return {"faults": get_store().faults(), "label": "CONTROLLED FAULT INJECTION (simulator only)"}


@router.delete("/fault")
def clear_faults(db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    get_store().clear_faults()
    notify.audit(db, user.username, "lab.fault_clear")
    db.commit()
    return {"faults": []}


@router.post("/sync-now")
def sync_now(db: Session = Depends(get_db)) -> dict:
    return sync_now_impl(db)
