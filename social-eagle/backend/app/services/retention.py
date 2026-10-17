"""Retention: delete old operational records per configured days. Never touches source data."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from .. import clock, kv
from ..models import AIRun, AuditLog, ChatMessage, Job, UserSession


def _rows(result: Any) -> int:
    return cast(CursorResult[Any], result).rowcount


def apply(session: Session) -> dict[str, Any]:
    days = kv.get(session, "retention_days") or {}
    now = clock.now()
    out = {}
    for model, key, col in ((AIRun, "ai_runs", AIRun.created_at), (AuditLog, "audit_log", AuditLog.at),
                            (ChatMessage, "chat_messages", ChatMessage.created_at)):
        n = int(days.get(key, 90))
        out[key] = _rows(session.execute(delete(model).where(col < now - timedelta(days=n))))
    out["finished_jobs"] = _rows(session.execute(delete(Job).where(Job.status.in_(["succeeded", "expired"]),
                                                                   Job.updated_at < now - timedelta(days=7))))
    out["expired_sessions"] = _rows(session.execute(delete(UserSession).where(UserSession.expires_at < clock.wall_now())))
    session.commit()
    return out
