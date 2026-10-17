"""Job handlers executed by the worker. Each returns a result dict or raises for retry."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..connectors.base import ModeViolation
from ..connectors.factory import get_adapter
from ..models import Action, Event, EventRegistration, Job, Member
from . import actions, automation, jobs, notify, sync


class Retry(Exception):
    def __init__(self, msg: str, delay_s: float | None = None) -> None:
        super().__init__(msg)
        self.delay_s = delay_s


def h_sync(session: Session, job: Job) -> dict[str, Any]:
    res = sync.sync_once(session, get_adapter("simulator"))
    if not res["ok"]:
        raise Retry(f"sync failed: {res.get('error')}: {res.get('detail')}", 60)
    for pid in res.pop("new_posts", []):
        jobs.enqueue(session, "evaluate_post", f"evaluate_post:{pid}", {"post_id": pid}, priority=4)
    session.commit()
    return res


def h_evaluate_post(session: Session, job: Job) -> dict[str, Any]:
    res = automation.evaluate_post(session, int(job.payload["post_id"]))
    if res["result"] == "ai_unavailable":
        raise Retry(f"AI unavailable: {res.get('reason')}", 120)
    return res


def h_draft_reply(session: Session, job: Job) -> dict[str, Any]:
    """Manual 'generate draft' request: always a draft, never auto-published."""
    from ..ai.answer import answer_question, format_reply
    from ..models import Post, SupportItem

    item = session.get(SupportItem, int(job.payload["support_item_id"]))
    if item is None:
        return {"result": "missing"}
    post = session.get(Post, item.post_id)
    assert post is not None
    asker = session.get(Member, post.author_id) if post.author_id else None
    thread = [p.body for p in session.execute(select(Post).where(Post.root_id == post.id).order_by(Post.created_at)).scalars()]
    res = answer_question(session, f"{post.title or ''}\n{post.body}".strip(), asker=asker, thread=thread,
                          refs={"post_id": post.id, "support_item_id": item.id, "requested_by": job.payload.get("requested_by")})
    if res.status == "unavailable":
        session.commit()
        raise Retry(f"AI unavailable: {res.reasons}", 120)
    payload = {"body": format_reply(res), "answer_status": res.status, "reasons": res.reasons, "citations": res.citations,
               "ai_label": "AI suggestion", "question_excerpt": post.body[:200]}
    existing = actions.pending_post_reply(session, post)
    if existing is not None and existing.state in ("drafted", "held"):
        existing.payload = payload
        existing.payload_version += 1
        existing.ai_run_id = res.ai_run_id
        existing.updated_at = clock.now()
        a = existing
    else:
        base = f"reply:{post.group_id}:{post.upstream_id}"
        n = session.execute(select(Action).where(Action.idempotency_key.like(f"{base}%"))).scalars().all()
        a, _ = actions.create_action(session, kind="reply", group_id=post.group_id, target_type="post",
                                     target_upstream_id=post.upstream_id, payload=payload, origin="ai_draft",
                                     idempotency_key=base if not n else f"{base}:r{len(n)}", support_item_id=item.id,
                                     ai_run_id=res.ai_run_id)
    if item.status in ("open", "assigned"):
        item.status = "drafted"
    session.commit()
    return {"result": "drafted", "action_id": a.id, "answer_status": res.status}


def _expand_bulk(session: Session, bulk: Action) -> dict[str, Any]:
    ev = session.execute(select(Event).filter_by(upstream_id=bulk.target_upstream_id)).scalar_one_or_none()
    if ev is None:
        bulk.state, bulk.error = "cancelled", "event no longer exists"
        session.commit()
        return {"result": "cancelled"}
    if ev.starts_at <= clock.now():
        bulk.state, bulk.error = "cancelled", "Expired: event already started (outdated reminder not sent)"
        session.commit()
        return {"result": "expired"}
    n = 0
    for reg, m in session.execute(select(EventRegistration, Member).join(Member, Member.id == EventRegistration.member_id)
                                  .where(EventRegistration.event_id == ev.id, Member.status == "active")).all():
        child, created = actions.create_action(
            session, kind="reminder", group_id=bulk.group_id, target_type="member", target_upstream_id=m.upstream_id,
            payload={"body": bulk.payload.get("body", ""), "parent_action_id": bulk.id}, origin=f"bulk:{bulk.id}",
            idempotency_key=f"{bulk.idempotency_key}:{m.upstream_id}", member_id=m.id, rule_id=bulk.rule_id)
        if created:
            child.state, child.approved_by, child.approved_at = "approved", bulk.approved_by, clock.now()
            actions.queue(session, child, expires_at=ev.starts_at)
            n += 1
    bulk.state = "sent"
    bulk.payload = {**bulk.payload, "expanded_children": n}
    session.commit()
    return {"result": "expanded", "children": n}


def h_publish_action(session: Session, job: Job) -> dict[str, Any]:
    action = session.get(Action, int(job.payload["action_id"]))
    if action is None:
        return {"result": "missing"}
    if job.expires_at and clock.now() > job.expires_at and action.state in ("approved", "queued"):
        action.state, action.error = "cancelled", "Expired before it could be sent (outdated after downtime)"
        session.commit()
        return {"result": "expired"}
    if action.kind == "bulk_member_message":
        if not action.approved_by or action.approved_by.startswith("rule:"):
            action.state = "held"
            session.commit()
            return {"result": "held", "reason": "bulk messages need human approval"}
        return _expand_bulk(session, action)
    try:
        res = actions.execute_action(session, action)
    except ModeViolation as e:
        action.state, action.error = "held", str(e)
        notify.raise_(session, f"mode:{action.id}", "error", "Blocked by run-mode policy", str(e))
        session.commit()
        return {"result": "blocked_by_mode", "reason": str(e)}
    if res["result"] == "paused":
        raise Retry("paused", 60)
    if res["result"] == "retry":
        raise Retry(res.get("reason", "retry"), res.get("delay_s"))
    if res["result"] == "unknown_outcome":
        jobs.enqueue(session, "reconcile_action", f"reconcile:{action.idempotency_key}:v{action.payload_version}:{action.id}",
                     {"action_id": action.id}, priority=2)
        session.commit()
    if res["result"] == "sent":
        sync.sync_once(session, get_adapter("simulator"))  # bring our own reply into the local thread
    return res


def h_reconcile_action(session: Session, job: Job) -> dict[str, Any]:
    action = session.get(Action, int(job.payload["action_id"]))
    if action is None or action.state not in ("unknown_outcome", "sending"):
        return {"result": "noop"}
    adapter = get_adapter("simulator")
    r = actions.reconcile(session, action, adapter)
    if r == "found":
        if actions._verify(session, action, adapter):
            action.state = "verified"
        session.commit()
        sync.sync_once(session, adapter)
        return {"result": "found", "state": action.state}
    if r == "absent":
        action.state = "queued"
        actions.queue(session, action)  # dedupe key unchanged → reuses the existing publish job if still queued
        pub = session.execute(select(Job).filter_by(dedupe_key=f"publish:{action.idempotency_key}:v{action.payload_version}")).scalar_one()
        if pub.status in ("succeeded", "failed", "expired"):
            pub.status, pub.run_after, pub.attempts = "queued", clock.now(), 0
        session.commit()
        return {"result": "absent_requeued"}
    action.state = "held"
    session.commit()
    return {"result": "held"}


def h_scan_rules(session: Session, job: Job) -> dict[str, Any]:
    return automation.scan_rules(session)


def h_backup(session: Session, job: Job) -> dict[str, Any]:
    from . import backup

    return backup.create_backup(label="scheduled")


def h_retention(session: Session, job: Job) -> dict[str, Any]:
    from . import retention

    return retention.apply(session)


def h_daily_summary(session: Session, job: Job) -> dict[str, Any]:
    from . import reports

    rep = reports.daily_summary(session)
    notify.info(session, f"Daily summary {rep['date']}", rep["text"])
    session.commit()
    return {"date": rep["date"]}


HANDLERS = {
    "sync": h_sync,
    "evaluate_post": h_evaluate_post,
    "draft_reply": h_draft_reply,
    "publish_action": h_publish_action,
    "reconcile_action": h_reconcile_action,
    "scan_rules": h_scan_rules,
    "backup": h_backup,
    "retention": h_retention,
    "daily_summary": h_daily_summary,
}
