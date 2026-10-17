"""Automation rules: turn observed events into drafts or (where explicitly allowed) automatic local actions.

Tiers (see docs/PERMISSIONS.md):
1. read/report automatically (sync, metrics) — always on.
2. draft initially — replies, reminders, onboarding, suggested moderation.
3. automatic permitted actions — only rules with mode=auto, within limits/quiet hours, and (in this phase)
   only evaluation_only rules targeting the local simulator.
4. explicit approval — consequential kinds are never automatic.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock, kv
from ..ai.answer import answer_question, format_reply
from ..config import get_settings
from ..models import Action, AutomationRule, Event, EventRegistration, Member, Post, SupportItem
from ..timeutil import local_date
from . import actions, metrics


def _rules(session: Session, trigger: str) -> list[AutomationRule]:
    return list(session.execute(select(AutomationRule).where(AutomationRule.trigger == trigger,
                                                             AutomationRule.enabled.is_(True))
                                .order_by(AutomationRule.id)).scalars())


def _auto_allowed(session: Session, rule: AutomationRule) -> tuple[bool, str | None]:
    s = get_settings()
    if rule.mode != "auto":
        return False, "rule is draft-only"
    if rule.evaluation_only and s.run_mode != "evaluation":
        return False, "evaluation-only rule outside evaluation mode"
    if s.run_mode != "evaluation":
        return False, "automatic external actions are disabled until live connection is approved"
    if kv.get(session, "paused"):
        return False, "global pause is on"
    if (kv.get(session, "ai_task_modes") or {}).get("faq_reply") == "draft_only":
        return False, "AI replies set to draft-only (quality/performance)"
    now = clock.now()
    if actions.rule_volume(session, rule.id, now - timedelta(hours=1)) >= rule.max_per_hour:
        return False, f"hourly limit {rule.max_per_hour} reached"
    if actions.rule_volume(session, rule.id, now - timedelta(days=1)) >= rule.max_per_day:
        return False, f"daily limit {rule.max_per_day} reached"
    return True, None


def evaluate_post(session: Session, post_id: int) -> dict[str, Any]:
    post = session.get(Post, post_id)
    if post is None or post.kind != "post" or post.deleted_at:
        return {"result": "skip", "reason": "not a live top-level post"}
    item = session.execute(select(SupportItem).filter_by(post_id=post.id)).scalar_one_or_none()
    if item is None or item.status not in ("open", "assigned"):
        return {"result": "skip", "reason": "no open support item"}
    if actions.pending_post_reply(session, post) is not None:
        return {"result": "skip", "reason": "reply already pending"}
    rules = [r for r in _rules(session, "new_question") if item.label in (r.conditions or {}).get("labels", ["question"])]
    if not rules:
        return {"result": "skip", "reason": "no matching enabled rule"}
    asker = session.get(Member, post.author_id) if post.author_id else None
    question = f"{post.title or ''}\n{post.body}".strip()
    thread = [p.body for p in session.execute(select(Post).where(Post.root_id == post.id).order_by(Post.created_at)).scalars()]
    result = answer_question(session, question, asker=asker, thread=thread,
                             refs={"post_id": post.id, "support_item_id": item.id})
    if result.status == "unavailable":
        session.commit()
        return {"result": "ai_unavailable", "reason": result.reasons}
    auto_rule = next((r for r in rules if r.mode == "auto"), None)
    draft_rule = next((r for r in rules if r.mode == "draft"), None) or auto_rule
    chosen = auto_rule if (auto_rule and result.auto_publish_ok
                           and len(question) <= (auto_rule.conditions or {}).get("max_question_chars", 1200)) else draft_rule
    assert chosen is not None
    a, created = actions.create_action(
        session, kind="reply", group_id=post.group_id, target_type="post", target_upstream_id=post.upstream_id,
        payload={"body": format_reply(result), "answer_status": result.status, "reasons": result.reasons,
                 "citations": result.citations, "ai_label": "AI suggestion", "question_excerpt": question[:200]},
        origin=f"rule:{chosen.id}" if chosen.mode == "auto" else "ai_draft", idempotency_key=f"reply:{post.group_id}:{post.upstream_id}",
        support_item_id=item.id, rule_id=chosen.id, ai_run_id=result.ai_run_id,
    )
    if not created:
        return {"result": "skip", "reason": "action exists"}
    item.status = "drafted"
    if result.status in ("blocked", "escalate", "restricted") or result.route == "support":
        item.priority = "high"
    outcome = {"result": "drafted", "action_id": a.id, "answer_status": result.status}
    if chosen.mode == "auto":
        ok, why = _auto_allowed(session, chosen)
        if ok:
            now = clock.now()
            run_after = actions.quiet_end_after(chosen, now) if actions.in_quiet_hours(chosen, now) else now
            actions.approve(session, a, f"rule:{chosen.id}", auto_rule=chosen)
            # approve() queued it immediately; re-queue respecting quiet hours and expiry
            from ..models import Job

            job = session.execute(select(Job).filter_by(dedupe_key=f"publish:{a.idempotency_key}:v{a.payload_version}")).scalar_one()
            job.run_after = run_after
            job.expires_at = now + timedelta(minutes=chosen.expire_after_minutes)
            outcome.update(result="auto_queued", run_after=run_after.isoformat())
        else:
            a.payload = {**a.payload, "auto_blocked_reason": why}
            outcome["auto_blocked_reason"] = why
    elif auto_rule is not None and not result.auto_publish_ok:
        a.payload = {**a.payload, "auto_blocked_reason": "; ".join(result.reasons) or f"answer status {result.status}"}
    session.commit()
    return outcome


def scan_rules(session: Session) -> dict[str, Any]:
    """Periodic scan for non-post triggers. Creates drafts only (dedupe keys prevent repeats)."""
    out: dict[str, int] = {"stalled": 0, "welcome": 0, "event_reminders": 0, "expired_reminders": 0}
    now = clock.now()
    gid = metrics.main_group_id(session)
    week = local_date(now).isocalendar()
    for rule in _rules(session, "stalled_progress"):
        days = int((rule.conditions or {}).get("days", 14))
        for mid in metrics.segment_members(session, "stalled_progress", {"days": days}, gid)[: rule.max_per_day]:
            m = session.get(Member, mid)
            nxt = metrics.next_lesson(session, mid)
            if m is None or nxt is None:
                continue
            body = (f"Hi {m.display_name.split()[0]}! 👋 (automated message) You last marked a lesson complete a while ago. "
                    f"Your suggested next lesson is “{nxt['lesson']}” in {nxt['course']}. Reply here if anything is blocking you.")
            _, created = actions.create_action(
                session, kind="member_message", group_id=gid, target_type="member", target_upstream_id=m.upstream_id,
                payload={"body": body, "next_lesson": nxt, "trigger": "stalled_progress"}, origin="rule_draft",
                idempotency_key=f"nudge:{m.upstream_id}:{week[0]}-W{week[1]}", member_id=m.id, rule_id=rule.id)
            out["stalled"] += int(created)
    for rule in _rules(session, "new_member"):
        for mid in metrics.segment_members(session, "new_members", {"days": 3}, gid)[: rule.max_per_day]:
            m = session.get(Member, mid)
            if m is None:
                continue
            body = (f"Welcome to the community, {m.display_name.split()[0]}! (automated message) Start with the Community "
                    "Onboarding Bootcamp, then introduce yourself in Introductions. Office hours are listed in the calendar.")
            _, created = actions.create_action(
                session, kind="member_message", group_id=gid, target_type="member", target_upstream_id=m.upstream_id,
                payload={"body": body, "trigger": "new_member"}, origin="rule_draft", idempotency_key=f"welcome:{m.upstream_id}",
                member_id=m.id, rule_id=rule.id)
            out["welcome"] += int(created)
    for rule in _rules(session, "event_upcoming"):
        hours = int((rule.conditions or {}).get("hours_before", 24))
        for ev in session.execute(select(Event).where(Event.group_id == gid, Event.cancelled.is_(False),
                                                      Event.starts_at > now, Event.starts_at <= now + timedelta(hours=hours))).scalars():
            n = len(session.execute(select(EventRegistration.id).where(EventRegistration.event_id == ev.id)).all())
            _, created = actions.create_action(
                session, kind="bulk_member_message", group_id=gid, target_type="event", target_upstream_id=ev.upstream_id,
                payload={"body": f"Reminder (automated): “{ev.title}” starts soon. See the calendar post for the link.",
                         "recipients": n, "event_starts_at": ev.starts_at.isoformat()},
                origin="rule_draft", idempotency_key=f"event-reminder:{ev.upstream_id}", rule_id=rule.id)
            out["event_reminders"] += int(created)
    # Outdated reminders: expire drafts for events that already started (no burst after sleep).
    for a in session.execute(select(Action).where(Action.kind == "bulk_member_message",
                                                  Action.state.in_(["drafted", "approved", "queued"]))).scalars():
        starts = a.payload.get("event_starts_at")
        if starts and now.isoformat() >= starts:
            a.state, a.error = "cancelled", "Expired: event already started (outdated reminder not sent)"
            out["expired_reminders"] += 1
    session.commit()
    return out
