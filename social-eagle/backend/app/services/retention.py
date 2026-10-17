"""Retention: delete old operational records per configured days. Never touches source data."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .. import clock, kv
from ..models import AIRun, AuditLog, ChatMessage, Job, UserSession


def apply(session: Session) -> dict[str, Any]:
    days = kv.get(session, "retention_days") or {}
    now = clock.now()
    out = {}
    for model, key, col in ((AIRun, "ai_runs", AIRun.created_at), (AuditLog, "audit_log", AuditLog.at),
                            (ChatMessage, "chat_messages", ChatMessage.created_at)):
        n = int(days.get(key, 90))
        out[key] = session.execute(delete(model).where(col < now - timedelta(days=n))).rowcount
    out["finished_jobs"] = session.execute(delete(Job).where(Job.status.in_(["succeeded", "expired"]),
                                                             Job.updated_at < now - timedelta(days=7))).rowcount
    out["expired_sessions"] = session.execute(delete(UserSession).where(UserSession.expires_at < clock.wall_now())).rowcount
    session.commit()
    return out
