"""Operator notifications (connector failures, held jobs, low disk...). Deduplicated by key."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..models import AuditLog, Notification


def raise_(session: Session, key: str, level: str, title: str, body: str) -> None:
    n = session.execute(select(Notification).filter_by(dedupe_key=key)).scalar_one_or_none()
    if n is None:
        session.add(Notification(at=clock.now(), level=level, title=title, body=body, dedupe_key=key, read=False))
    else:
        n.at, n.level, n.title, n.body, n.read = clock.now(), level, title, body, False


def resolve(session: Session, key: str) -> None:
    n = session.execute(select(Notification).filter_by(dedupe_key=key)).scalar_one_or_none()
    if n is not None and not n.read:
        n.read = True
        n.body = (n.body or "") + " — resolved."


def info(session: Session, title: str, body: str) -> None:
    session.add(Notification(at=clock.now(), level="info", title=title, body=body, read=False))


def audit(session: Session, actor: str, action: str, **detail: object) -> None:
    session.add(AuditLog(at=clock.now(), actor=actor, action=action, detail=detail))
