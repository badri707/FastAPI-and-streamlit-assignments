from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..models import Action, ActionAttempt, AIRun, Job, Member
from ..security import require_admin
from ..services import actions, jobs, notify
from ..timeutil import iso

router = APIRouter(prefix="/api", tags=["actions"], dependencies=[Depends(require_admin)])


def _action(a: Action, db: Session, full: bool = False) -> dict:
    out = {"id": a.id, "kind": a.kind, "state": a.state, "origin": a.origin, "target_type": a.target_type,
           "target_upstream_id": a.target_upstream_id, "member_id": a.member_id, "support_item_id": a.support_item_id,
           "consequential": a.consequential, "simulated": a.simulated, "delivery_target": a.delivery_target,
           "approved_by": a.approved_by, "approved_at": iso(a.approved_at), "remote_id": a.remote_id, "error": a.error,
           "payload_version": a.payload_version, "created_at": iso(a.created_at), "updated_at": iso(a.updated_at),
           "rule_id": a.rule_id, "body": a.payload.get("body"), "answer_status": a.payload.get("answer_status"),
           "auto_blocked_reason": a.payload.get("auto_blocked_reason"), "reasons": a.payload.get("reasons"),
           "stage": {"drafted": "Drafted", "approved": "Approved", "queued": "Approved — waiting to send", "sending": "Sending",
                     "sent": "Sent (simulated)" if a.simulated else "Sent", "verified": "Verified in thread (simulated)" if a.simulated else "Verified",
                     "unknown_outcome": "Unknown outcome — reconciling", "held": "Held for review", "failed": "Failed",
                     "rejected": "Rejected", "cancelled": "Cancelled"}.get(a.state, a.state)}
    if a.member_id:
        m = db.get(Member, a.member_id)
        out["member_name"] = m.display_name if m else None
    if full:
        out["payload"] = a.payload
        out["attempts"] = [{"no": t.attempt_no, "outcome": t.outcome, "detail": t.detail, "at": iso(t.started_at)}
                           for t in db.execute(select(ActionAttempt).where(ActionAttempt.action_id == a.id)
                                               .order_by(ActionAttempt.attempt_no)).scalars()]
        if a.ai_run_id:
            r = db.get(AIRun, a.ai_run_id)
            if r:
                out["ai_run"] = {"id": r.id, "status": r.status, "model": r.model, "digest": (r.model_digest or "")[:19],
                                 "policy_version": r.policy_version, "retrieved": r.retrieved, "latency_ms": r.latency_ms,
                                 "detail": r.detail}
    return out


@router.get("/actions")
def list_actions(state: str | None = None, kind: str | None = None, page: int = Query(1, ge=1),
                 page_size: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)) -> dict:
    qy = select(Action)
    if state:
        qy = qy.where(Action.state.in_(state.split(",")))
    if kind:
        qy = qy.where(Action.kind == kind)
    total = db.execute(select(func.count()).select_from(qy.subquery())).scalar()
    rows = db.execute(qy.order_by(Action.updated_at.desc(), Action.id.desc()).offset((page - 1) * page_size).limit(page_size)).scalars()
    counts = dict(db.execute(select(Action.state, func.count()).group_by(Action.state)).all())
    return {"total": total, "rows": [_action(a, db) for a in rows], "counts": counts}


@router.get("/actions/{action_id}")
def get_action(action_id: int, db: Session = Depends(get_db)) -> dict:
    a = db.get(Action, action_id)
    if a is None:
        raise HTTPException(404, "action not found")
    return _action(a, db, full=True)


class EditIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


@router.put("/actions/{action_id}")
def edit_action(action_id: int, body: EditIn, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    a = db.get(Action, action_id)
    if a is None:
        raise HTTPException(404, "action not found")
    try:
        actions.edit_draft(db, a, body.body, user.username)
    except actions.ActionError as e:
        raise HTTPException(409, str(e)) from e
    db.commit()
    return _action(a, db, full=True)


@router.post("/actions/{action_id}/approve")
def approve_action(action_id: int, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    a = db.get(Action, action_id)
    if a is None:
        raise HTTPException(404, "action not found")
    try:
        actions.approve(db, a, user.username)
    except actions.ActionError as e:
        raise HTTPException(409, str(e)) from e
    db.commit()
    return _action(a, db, full=True)


class RejectIn(BaseModel):
    reason: str = Field("", max_length=500)


@router.post("/actions/{action_id}/reject")
def reject_action(action_id: int, body: RejectIn, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    a = db.get(Action, action_id)
    if a is None:
        raise HTTPException(404, "action not found")
    try:
        actions.reject(db, a, user.username, body.reason)
    except actions.ActionError as e:
        raise HTTPException(409, str(e)) from e
    db.commit()
    return _action(a, db, full=True)


class ModerationIn(BaseModel):
    member_id: int
    kind: str = Field(pattern="^(ban|remove_member)$")
    reason: str = Field(min_length=3, max_length=500)


@router.post("/actions/moderation")
def propose_moderation(body: ModerationIn, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    """Creates a DRAFT consequential action; it still needs an explicit approval step."""
    m = db.get(Member, body.member_id)
    if m is None:
        raise HTTPException(404, "member not found")
    a, _ = actions.create_action(db, kind=body.kind, group_id=m.group_id, target_type="member", target_upstream_id=m.upstream_id,
                                 payload={"reason": body.reason, "body": f"{body.kind} proposed: {body.reason}"}, origin="manual",
                                 idempotency_key=f"{body.kind}:{m.upstream_id}:{clock.now():%Y%m%d%H%M%S}", member_id=m.id)
    db.commit()
    return _action(a, db, full=True)


@router.get("/jobs")
def list_jobs(status: str | None = None, kind: str | None = None, limit: int = Query(100, ge=1, le=500),
              db: Session = Depends(get_db)) -> dict:
    qy = select(Job)
    if status:
        qy = qy.where(Job.status.in_(status.split(",")))
    if kind:
        qy = qy.where(Job.kind == kind)
    rows = db.execute(qy.order_by(Job.id.desc()).limit(limit)).scalars()
    return {"stats": jobs.queue_stats(db), "rows": [
        {"id": j.id, "kind": j.kind, "dedupe_key": j.dedupe_key, "status": j.status, "attempts": j.attempts,
         "max_attempts": j.max_attempts, "run_after": iso(j.run_after), "expires_at": iso(j.expires_at),
         "last_error": j.last_error, "result": j.result, "created_at": iso(j.created_at), "updated_at": iso(j.updated_at)}
        for j in rows]}


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    j = db.get(Job, job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    return {"id": j.id, "kind": j.kind, "status": j.status, "attempts": j.attempts, "last_error": j.last_error, "result": j.result}


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    j = db.get(Job, job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    if j.status not in ("failed", "held"):
        raise HTTPException(409, "Only failed or held jobs can be retried")
    j.status, j.attempts, j.run_after, j.last_error = "queued", 0, clock.now(), None
    if j.kind == "publish_action":
        a = db.get(Action, j.payload.get("action_id"))
        if a and a.state == "held":
            a.state = "queued"
    notify.audit(db, user.username, "job.retry", job_id=job_id)
    db.commit()
    return {"id": j.id, "status": j.status}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    j = db.get(Job, job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    if j.status not in ("queued", "held", "failed"):
        raise HTTPException(409, "Only queued/held/failed jobs can be cancelled (a running job finishes its attempt)")
    j.status = "cancelled"
    if j.kind == "publish_action":
        a = db.get(Action, j.payload.get("action_id"))
        if a and a.state in ("queued", "approved", "held"):
            a.state, a.error = "cancelled", f"cancelled by {user.username}"
    notify.audit(db, user.username, "job.cancel", job_id=job_id)
    db.commit()
    return {"id": j.id, "status": j.status}
