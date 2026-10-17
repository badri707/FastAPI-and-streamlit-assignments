from __future__ import annotations

import platform
import shutil
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock, kv
from ..ai.provider import get_provider
from ..config import get_settings
from ..connectors.base import ModeViolation
from ..connectors.factory import get_adapter
from ..db import get_db
from ..models import Action, Notification, SyncState, User, WorkerHeartbeat
from ..security import require_admin
from ..services import jobs, notify
from ..timeutil import fmt_local, iso

router = APIRouter(prefix="/api/system", tags=["system"])


def worker_status(db: Session) -> dict:
    hb = db.execute(select(WorkerHeartbeat).order_by(WorkerHeartbeat.wall_beat_at.desc())).scalars().first()
    if hb is None:
        return {"state": "never_started", "detail": "The worker has not run yet. Start it with scripts/start."}
    age = (clock.wall_now() - (hb.wall_beat_at or hb.beat_at)).total_seconds()
    state = "stopped" if hb.status == "stopped" else ("alive" if age < 30 else "unresponsive")
    return {"state": state, "status": hb.status, "pid": hb.pid, "last_beat_age_s": round(age, 1),
            "current_job": hb.current_job, "started_at": iso(hb.started_at)}


@router.get("/status")
def status(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    s = get_settings()
    sync_rows = db.execute(select(SyncState)).scalars().all()
    try:
        conn = get_adapter("simulator").health()
    except ModeViolation as e:
        conn = {"ok": False, "status": "mode_violation", "detail": str(e)}
    du = shutil.disk_usage(s.data_dir)
    ssd = None
    if s.external_ssd_path:
        ssd = {"path": str(s.external_ssd_path), "present": s.external_ssd_path.exists()}
    in_progress = db.execute(select(Action).where(Action.state.in_(["sending", "unknown_outcome"]))).scalars().all()
    return {
        "run_mode": s.run_mode,
        "evaluation_banner": "Evaluation — synthetic community data" if s.run_mode == "evaluation" else None,
        "live_connection": "deferred until approval",
        "clock": {**clock.describe(), "local": fmt_local(clock.now()), "timezone": s.display_tz},
        "paused": bool(kv.get(db, "paused")), "paused_reason": kv.get(db, "paused_reason"),
        "actions_in_progress": [{"id": a.id, "state": a.state, "kind": a.kind} for a in in_progress],
        "worker": worker_status(db), "queue": jobs.queue_stats(db),
        "sync": [{"source": r.source, "status": r.status, "last_success": iso(r.last_success_at), "last_error": r.last_error,
                  "cursor": r.cursor, "coverage": r.coverage,
                  "freshness_s": (clock.now() - r.last_success_at).total_seconds() if r.last_success_at else None} for r in sync_rows],
        "connection": conn, "ai": get_provider().health(),
        "disk": {"free_mb": round(du.free / 1e6), "low": du.free / 1e6 < s.min_free_disk_mb, "data_dir": str(s.data_dir)},
        "external_ssd": ssd or {"configured": False, "note": "Not required. Optional for backups/archives once verified."},
        "availability_note": "Runs only while this computer is awake and the app is started. Jobs pause during sleep, "
                             "shutdown or network loss. Not a 24/7 service.",
        "platform": {"python": platform.python_version(), "machine": platform.machine(), "system": platform.system()},
    }


class PauseIn(BaseModel):
    paused: bool
    reason: str | None = Field(None, max_length=300)


@router.post("/pause")
def pause(body: PauseIn, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict:
    kv.put(db, "paused", body.paused)
    kv.put(db, "paused_reason", body.reason if body.paused else None)
    notify.audit(db, user.username, "system.pause" if body.paused else "system.resume", reason=body.reason)
    in_progress = db.execute(select(Action).where(Action.state.in_(["sending", "unknown_outcome"]))).scalars().all()
    db.commit()
    return {"paused": body.paused, "in_progress": [{"id": a.id, "state": a.state} for a in in_progress],
            "explanation": ("New outbound actions will not start. Actions already marked 'sending' or 'unknown outcome' "
                            "will be reconciled when resumed; nothing new is sent while paused.") if body.paused else "Resumed."}


class ClockIn(BaseModel):
    advance_minutes: int = Field(ge=1, le=60 * 24 * 30)


@router.post("/clock/advance")
def advance_clock(body: ClockIn, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict:
    if get_settings().run_mode != "evaluation":
        raise HTTPException(403, "The test clock can only be changed in evaluation mode")
    new = clock.advance(db, timedelta(minutes=body.advance_minutes))
    notify.audit(db, user.username, "clock.advance", minutes=body.advance_minutes)
    db.commit()
    return {"now": iso(new), "local": fmt_local(new)}


@router.get("/notifications")
def notifications(unread_only: bool = False, db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[dict]:
    q = select(Notification).order_by(Notification.at.desc()).limit(100)
    if unread_only:
        q = q.where(Notification.read.is_(False))
    return [{"id": n.id, "at": iso(n.at), "level": n.level, "title": n.title, "body": n.body, "read": n.read}
            for n in db.execute(q).scalars()]


@router.post("/notifications/{nid}/read")
def mark_read(nid: int, db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    n = db.get(Notification, nid)
    if n is None:
        raise HTTPException(404, "not found")
    n.read = True
    db.commit()
    return {"ok": True}


@router.get("/diagnostics")
def diagnostics(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    from ..models import AIRun, AuditLog

    runs = db.execute(select(AIRun).order_by(AIRun.id.desc()).limit(30)).scalars().all()
    audit = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(50)).scalars().all()
    lat = sorted(r.latency_ms for r in runs if r.latency_ms)
    return {
        "ai_runs": [{"id": r.id, "task": r.task, "status": r.status, "model": r.model, "digest": (r.model_digest or "")[:19],
                     "policy": r.policy_version, "latency_ms": r.latency_ms, "retrieved": r.retrieved, "detail": r.detail,
                     "refs": r.refs, "at": iso(r.created_at)} for r in runs],
        "ai_latency_ms": {"n": len(lat), "median": lat[len(lat) // 2] if lat else None, "max": lat[-1] if lat else None},
        "audit": [{"at": iso(a.at), "actor": a.actor, "action": a.action, "detail": a.detail} for a in audit],
    }


class SettingsIn(BaseModel):
    thresholds: dict | None = None
    ai_task_modes: dict | None = None
    dataset_selection: list[str] | None = None
    retention_days: dict | None = None


@router.get("/settings")
def get_settings_api(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    return {k: kv.get(db, k) for k in ("thresholds", "ai_task_modes", "dataset_selection", "retention_days")}


@router.put("/settings")
def put_settings(body: SettingsIn, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict:
    data = body.model_dump(exclude_none=True)
    if "dataset_selection" in data and (
            not data["dataset_selection"] or any(d != "synthetic" and not d.startswith("import:") for d in data["dataset_selection"])):
            raise HTTPException(400, "dataset_selection must list 'synthetic' and/or 'import:<id>' labels")
    if "ai_task_modes" in data:
        allowed = {"faq_reply": {"draft", "draft_only"}, "owner_chat": {"enabled", "disabled"}, "classify": {"enabled", "disabled"}}
        for k, v in data["ai_task_modes"].items():
            if k not in allowed or v not in allowed[k]:
                raise HTTPException(400, f"invalid ai_task_modes {k}={v}")
    if "thresholds" in data:
        merged = {**(kv.get(db, "thresholds") or {}), **data["thresholds"]}
        for k in ("new_member_days", "quiet_days", "stalled_progress_days", "unanswered_hours"):
            if not isinstance(merged.get(k), int) or not 1 <= merged[k] <= 365:
                raise HTTPException(400, f"threshold {k} must be an integer 1–365")
        data["thresholds"] = merged
    for k, v in data.items():
        kv.put(db, k, v)
    notify.audit(db, user.username, "settings.update", keys=list(data))
    db.commit()
    return {k: kv.get(db, k) for k in ("thresholds", "ai_task_modes", "dataset_selection", "retention_days")}
