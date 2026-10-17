from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..config import get_settings
from ..db import get_db
from ..models import AutomationRule
from ..security import require_admin
from ..services import notify
from ..services.actions import CONSEQUENTIAL_KINDS
from ..timeutil import iso

router = APIRouter(prefix="/api/automation", tags=["automation"], dependencies=[Depends(require_admin)])
TRIGGERS = {"new_question", "stalled_progress", "new_member", "event_upcoming"}
ACTION_KINDS = {"reply", "member_message", "bulk_member_message"}
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


def _rule(r: AutomationRule) -> dict:
    return {"id": r.id, "name": r.name, "trigger": r.trigger, "conditions": r.conditions, "action_kind": r.action_kind,
            "mode": r.mode, "enabled": r.enabled, "quiet_start": r.quiet_start, "quiet_end": r.quiet_end,
            "max_per_hour": r.max_per_hour, "max_per_day": r.max_per_day, "expire_after_minutes": r.expire_after_minutes,
            "evaluation_only": r.evaluation_only, "description": r.description, "updated_at": iso(r.updated_at),
            "consequential": r.action_kind in CONSEQUENTIAL_KINDS}


@router.get("/rules")
def rules(db: Session = Depends(get_db)) -> dict:
    return {"rules": [_rule(r) for r in db.execute(select(AutomationRule).order_by(AutomationRule.id)).scalars()],
            "triggers": sorted(TRIGGERS), "action_kinds": sorted(ACTION_KINDS),
            "policy": "Automatic mode is only allowed for reply rules, never for consequential actions, and in this phase only "
                      "against the local simulator."}


class RuleIn(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    trigger: str
    action_kind: str
    mode: str = Field("draft", pattern="^(draft|auto)$")
    enabled: bool = False
    conditions: dict = Field(default_factory=dict)
    quiet_start: str | None = Field(None, pattern=HHMM)
    quiet_end: str | None = Field(None, pattern=HHMM)
    max_per_hour: int = Field(5, ge=0, le=100)
    max_per_day: int = Field(30, ge=0, le=1000)
    expire_after_minutes: int = Field(240, ge=5, le=60 * 24 * 14)
    description: str | None = Field(None, max_length=1000)


def _validate(body: RuleIn) -> None:
    if body.trigger not in TRIGGERS or body.action_kind not in ACTION_KINDS:
        raise HTTPException(400, "unknown trigger or action kind")
    if body.mode == "auto" and (body.action_kind in CONSEQUENTIAL_KINDS or body.action_kind != "reply"):
        raise HTTPException(400, "Only reply rules may run automatically; bulk/consequential actions always need approval")
    if body.mode == "auto" and get_settings().run_mode != "evaluation":
        raise HTTPException(400, "Automatic rules are disabled outside evaluation mode in this phase")


@router.post("/rules")
def create_rule(body: RuleIn, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    _validate(body)
    now = clock.now()
    r = AutomationRule(**body.model_dump(), evaluation_only=body.mode == "auto", created_at=now, updated_at=now)
    db.add(r)
    notify.audit(db, user.username, "rule.create", name=body.name, mode=body.mode)
    db.commit()
    return _rule(r)


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, body: RuleIn, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    r = db.get(AutomationRule, rule_id)
    if r is None:
        raise HTTPException(404, "rule not found")
    _validate(body)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    if body.mode == "auto":
        r.evaluation_only = True
    r.updated_at = clock.now()
    notify.audit(db, user.username, "rule.update", rule_id=rule_id, mode=body.mode, enabled=body.enabled)
    db.commit()
    return _rule(r)
