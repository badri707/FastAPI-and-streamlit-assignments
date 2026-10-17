"""Outward actions: drafting, approval, execution, verification and reconciliation.

State machine:
  drafted → approved → queued → sending → sent → verified
  drafted → rejected | cancelled          sending → unknown_outcome → (reconciled) sent | queued | held
  queued/approved → expired (outdated after sleep) | held (needs review) | failed (max attempts)

Every write goes through `execute_action`, which: re-checks mode, pause, approval and target state immediately
before sending; uses a stable idempotency key; records each attempt; treats timeout-after-send as an
UNKNOWN outcome that must be reconciled before any retry; and verifies the remote result. Exactly-once is NOT
claimed: it holds only to the extent the target honours idempotency keys or supports lookups.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock, kv
from ..config import get_settings
from ..connectors.base import (
    AuthExpired,
    CommunityAdapter,
    ConnectorError,
    ConnectorUnavailable,
    ModeViolation,
    RateLimited,
    TimeoutUnknownOutcome,
)
from ..connectors.factory import delivery_target, get_adapter
from ..connectors.simulator import body_signature
from ..models import Action, ActionAttempt, AutomationRule, Group, Member, Post, SupportItem
from ..timeutil import IST
from . import jobs, notify

CONSEQUENTIAL_KINDS = {"ban", "remove_member", "delete_post", "refund", "billing_change", "permission_change",
                       "bulk_member_message"}
OPEN_STATES = ("drafted", "approved", "queued", "sending", "unknown_outcome", "held")


class ActionError(Exception):
    pass


def _now() -> datetime:
    return clock.now()


def create_action(
    session: Session,
    *,
    kind: str,
    group_id: int,
    target_type: str,
    target_upstream_id: str,
    payload: dict[str, Any],
    origin: str,
    idempotency_key: str,
    member_id: int | None = None,
    support_item_id: int | None = None,
    rule_id: int | None = None,
    ai_run_id: int | None = None,
) -> tuple[Action, bool]:
    existing = session.execute(select(Action).filter_by(idempotency_key=idempotency_key)).scalar_one_or_none()
    if existing is not None:
        return existing, False
    s = get_settings()
    a = Action(kind=kind, group_id=group_id, target_type=target_type, target_upstream_id=target_upstream_id,
               member_id=member_id, support_item_id=support_item_id, payload=payload, payload_version=1, state="drafted",
               origin=origin, rule_id=rule_id, ai_run_id=ai_run_id, consequential=kind in CONSEQUENTIAL_KINDS,
               simulated=s.run_mode == "evaluation", delivery_target=delivery_target(s),
               idempotency_key=idempotency_key, created_at=_now(), updated_at=_now())
    session.add(a)
    session.flush()
    notify.audit(session, origin, "action.drafted", action_id=a.id, kind=kind, target=target_upstream_id)
    return a, True


def edit_draft(session: Session, action: Action, body: str, actor: str) -> Action:
    if action.state not in ("drafted", "held"):
        raise ActionError(f"Only drafts can be edited (state={action.state})")
    action.payload = {**action.payload, "body": body, "edited_by": actor}
    action.payload_version += 1
    action.updated_at = _now()
    notify.audit(session, actor, "action.edited", action_id=action.id, version=action.payload_version)
    return action


def approve(session: Session, action: Action, actor: str, *, auto_rule: AutomationRule | None = None) -> Action:
    if action.state not in ("drafted", "held"):
        raise ActionError(f"Cannot approve an action in state {action.state}")
    if action.consequential and auto_rule is not None:
        raise ActionError("Consequential actions always require explicit human approval")
    action.state = "approved"
    action.approved_by = actor
    action.approved_at = _now()
    action.updated_at = _now()
    queue(session, action)
    notify.audit(session, actor, "action.approved", action_id=action.id, consequential=action.consequential)
    return action


def queue(session: Session, action: Action, run_after: datetime | None = None, expires_at: datetime | None = None) -> None:
    action.state = "queued"
    action.updated_at = _now()
    jobs.enqueue(session, "publish_action", f"publish:{action.idempotency_key}:v{action.payload_version}",
                 {"action_id": action.id}, run_after=run_after, expires_at=expires_at, priority=3, max_attempts=5)


def reject(session: Session, action: Action, actor: str, reason: str = "") -> Action:
    if action.state not in ("drafted", "held", "approved", "queued"):
        raise ActionError(f"Cannot reject an action in state {action.state}")
    action.state = "rejected"
    action.error = reason or None
    action.updated_at = _now()
    if action.support_item_id:
        item = session.get(SupportItem, action.support_item_id)
        if item and item.status == "drafted":
            item.status = "open"
    notify.audit(session, actor, "action.rejected", action_id=action.id, reason=reason)
    return action


def _attempt(session: Session, action: Action, outcome: str, detail: str = "") -> ActionAttempt:
    n = session.execute(select(func.count()).where(ActionAttempt.action_id == action.id)).scalar() or 0
    at = ActionAttempt(action_id=action.id, attempt_no=n + 1, started_at=_now(), finished_at=_now(), outcome=outcome,
                       detail=detail[:1000])
    session.add(at)
    return at


def in_quiet_hours(rule: AutomationRule, at: datetime) -> bool:
    if not rule.quiet_start or not rule.quiet_end:
        return False
    local = at.replace(tzinfo=UTC).astimezone(IST)
    hm = local.strftime("%H:%M")
    s, e = rule.quiet_start, rule.quiet_end
    return (s <= hm < e) if s < e else (hm >= s or hm < e)


def quiet_end_after(rule: AutomationRule, at: datetime) -> datetime:
    t = at
    for _ in range(24 * 4):
        if not in_quiet_hours(rule, t):
            return t
        t += timedelta(minutes=15)
    return t


def rule_volume(session: Session, rule_id: int, since: datetime) -> int:
    return session.execute(select(func.count()).where(
        Action.rule_id == rule_id, Action.created_at >= since,
        Action.state.in_(["approved", "queued", "sending", "sent", "verified", "unknown_outcome"]),
    )).scalar() or 0


def _adapter_for(action: Action) -> CommunityAdapter:
    s = get_settings()
    if s.run_mode == "evaluation":
        if not action.simulated or action.delivery_target != "local-simulator":
            raise ModeViolation("Evaluation mode: only simulated actions targeting the local simulator may execute")
        return get_adapter("simulator", s)
    raise ModeViolation("Live delivery is not implemented in this phase (deferred until approval)")


def _group_upstream(session: Session, action: Action) -> str:
    g = session.get(Group, action.group_id)
    if g is None:
        raise ActionError("group missing")
    return g.upstream_id


def _recheck(session: Session, action: Action, adapter: CommunityAdapter) -> str | None:
    """Return a reason to NOT send, or None. Re-checks current source state right before execution."""
    if action.consequential and not action.approved_by:
        return "Consequential action lacks explicit approval"
    if action.kind == "reply":
        thread = adapter.list_thread(action.target_upstream_id)
        root = next((p for p in thread if p["upstream_id"] == action.target_upstream_id), None)
        if root is None or root.get("deleted_at"):
            return "Target post no longer exists"
        if action.origin.startswith("rule:"):
            others = [p for p in thread if p["upstream_id"] != root["upstream_id"] and p["author_id"] != root["author_id"]
                      and p.get("client_ref") != _key(action)]
            if others:
                return "Thread already received a reply since the draft was prepared (auto-reply superseded)"
        if action.support_item_id:
            item = session.get(SupportItem, action.support_item_id)
            if item and item.status in ("resolved", "dismissed"):
                return f"Support item was {item.status} by staff"
    if action.member_id:
        m = session.get(Member, action.member_id)
        if m is None or m.status != "active":
            return "Target member is no longer active"
    return None


def _key(action: Action) -> str:
    return f"{action.idempotency_key}:v{action.payload_version}"


def _send(adapter: CommunityAdapter, session: Session, action: Action) -> Any:
    g = _group_upstream(session, action)
    body = action.payload.get("body", "")
    if action.kind == "reply":
        return adapter.publish_comment(group_upstream_id=g, parent_upstream_id=action.target_upstream_id, body=body,
                                       idempotency_key=_key(action))
    if action.kind in ("member_message", "reminder", "onboarding"):
        return adapter.send_member_message(group_upstream_id=g, member_upstream_id=action.target_upstream_id, body=body,
                                           idempotency_key=_key(action))
    if action.kind in ("ban", "remove_member"):
        return adapter.apply_member_action(group_upstream_id=g, member_upstream_id=action.target_upstream_id,
                                           action="ban" if action.kind == "ban" else "remove", params=action.payload,
                                           idempotency_key=_key(action))
    raise ActionError(f"Action kind {action.kind!r} has no supported delivery")


def _lookup_kind(action: Action) -> str:
    return {"reply": "reply", "ban": "member_action", "remove_member": "member_action"}.get(action.kind, "message")


def _verify(session: Session, action: Action, adapter: CommunityAdapter) -> bool:
    if action.kind == "reply":
        thread = adapter.list_thread(action.target_upstream_id)
        sig = body_signature(action.payload.get("body", ""))
        return any(p["upstream_id"] == action.remote_id and body_signature(p["body"]) == sig for p in thread)
    found = adapter.find_by_idempotency_key(_lookup_kind(action), _key(action))
    return found is not None and found.get("upstream_id") == action.remote_id


def reconcile(session: Session, action: Action, adapter: CommunityAdapter) -> str:
    """Resolve an unknown outcome. Returns 'found' | 'absent' | 'unsupported'."""
    if not adapter.supports("reconcile.thread_lookup"):
        return "unsupported"
    found = adapter.find_by_idempotency_key(_lookup_kind(action), _key(action))
    if found:
        action.remote_id = found["upstream_id"]
        action.state = "sent"
        _attempt(session, action, "reconciled_found", f"remote_id={action.remote_id}")
        return "found"
    _attempt(session, action, "reconciled_absent", "no remote record with this idempotency key")
    return "absent"


def execute_action(session: Session, action: Action) -> dict[str, Any]:
    """Run one delivery attempt. Caller (worker job) handles retry scheduling based on the return value."""
    if action.state in ("sent", "verified", "rejected", "cancelled"):
        return {"result": "noop", "state": action.state}
    if kv.get(session, "paused"):
        return {"result": "paused"}
    adapter = _adapter_for(action)  # raises ModeViolation outside evaluation mode
    # A previous attempt may have crashed mid-send or timed out: reconcile BEFORE any new send.
    if action.state in ("sending", "unknown_outcome"):
        r = reconcile(session, action, adapter)
        if r == "unsupported":
            action.state = "held"
            action.error = "Unknown outcome and the target cannot be checked; held for human review"
            session.commit()
            return {"result": "held", "reason": action.error}
        if r == "found":
            if _verify(session, action, adapter):
                action.state = "verified"
            session.commit()
            return {"result": "reconciled", "state": action.state}
        # absent: safe to send again
    reason = _recheck(session, action, adapter)
    if reason:
        action.state = "cancelled"
        action.error = reason
        _attempt(session, action, "blocked", reason)
        if action.support_item_id:
            item = session.get(SupportItem, action.support_item_id)
            if item and item.status == "drafted":
                item.status = "answered" if item.first_response_at else "open"
        session.commit()
        return {"result": "cancelled", "reason": reason}
    action.state = "sending"
    action.updated_at = _now()
    session.commit()  # durable marker: a crash from here on is reconciled on restart
    try:
        res = _send(adapter, session, action)
    except TimeoutUnknownOutcome as e:
        action.state = "unknown_outcome"
        action.error = str(e)
        _attempt(session, action, "timeout_unknown", str(e))
        session.commit()
        return {"result": "unknown_outcome", "reason": str(e)}
    except RateLimited as e:
        action.state = "queued"
        _attempt(session, action, "error", f"rate_limited: {e}")
        session.commit()
        return {"result": "retry", "delay_s": e.retry_after_s, "reason": str(e)}
    except (AuthExpired, ConnectorUnavailable) as e:
        action.state = "queued"
        action.error = f"{e.kind}: {e}"
        _attempt(session, action, "error", action.error)
        notify.raise_(session, "delivery", "error", "Delivery failing", action.error)
        session.commit()
        return {"result": "retry", "reason": action.error}
    except ConnectorError as e:
        action.state = "failed"
        action.error = f"{e.kind}: {e}"
        _attempt(session, action, "error", action.error)
        session.commit()
        return {"result": "failed", "reason": action.error}
    action.remote_id = res.remote_id
    action.state = "sent"
    action.error = None
    _attempt(session, action, "sent", f"remote_id={res.remote_id} simulated={action.simulated}")
    session.commit()
    try:
        if _verify(session, action, adapter):
            action.state = "verified"
            _attempt(session, action, "verified", "remote record matches payload")
    except ConnectorError as e:
        _attempt(session, action, "error", f"verification deferred: {e}")
    if action.support_item_id and action.kind == "reply":
        item = session.get(SupportItem, action.support_item_id)
        if item and item.status in ("open", "assigned", "drafted"):
            item.status = "answered"
            item.updated_at = _now()
    session.commit()
    return {"result": "sent", "state": action.state, "remote_id": action.remote_id}


def pending_post_reply(session: Session, post: Post) -> Action | None:
    return session.execute(select(Action).where(Action.kind == "reply", Action.target_upstream_id == post.upstream_id,
                                                Action.state.in_(OPEN_STATES))).scalars().first()
