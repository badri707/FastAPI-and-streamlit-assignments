"""Support inbox rules.

"Appears unanswered" = no reply from anyone other than the asker. This is an observed fact about the
thread, distinct from a human-verified resolution (status=resolved with human_verified=True) and from
AI classifications (label_source starting with "ai:").
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..models import Member, Post, SupportItem

QUESTION_START = re.compile(r"^\s*(how|what|why|when|where|which|who|can|could|should|is|are|do|does|did|will|would)\b", re.I)
UNANSWERED_STATES = ("open", "assigned", "drafted")


def classify_rule(post: Post, keywords: list[str]) -> tuple[bool, str, str]:
    """Returns (is_support_item, label, priority) using transparent rule v1."""
    text = f"{post.title or ''} {post.body}".lower()
    has_kw = any(k in text for k in keywords)
    if post.category == "Help Desk" or has_kw:
        return True, "needs_support", "high"
    if post.category == "Questions" or "?" in text or QUESTION_START.match(post.body or ""):
        return True, "question", "normal"
    return False, "", ""


def maybe_open_support_item(session: Session, post: Post, thresholds: dict[str, Any]) -> SupportItem | None:
    if post.kind != "post" or post.deleted_at is not None:
        return None
    author = session.get(Member, post.author_id) if post.author_id else None
    if author is not None and (author.is_bot or author.is_staff):
        return None
    ok, label, prio = classify_rule(post, thresholds.get("support_keywords", []))
    if not ok:
        return None
    existing = session.execute(select(SupportItem).filter_by(post_id=post.id)).scalar_one_or_none()
    if existing:
        return existing
    item = SupportItem(group_id=post.group_id, post_id=post.id, status="open", label=label, label_source="rule:v1",
                       priority=prio, created_at=post.created_at, updated_at=clock.now())
    session.add(item)
    session.flush()
    return item


def record_response(session: Session, root_id: int, reply: Post) -> None:
    item = session.execute(select(SupportItem).filter_by(post_id=root_id)).scalar_one_or_none()
    if item is None:
        return
    root = session.get(Post, root_id)
    if root is None or reply.author_id == root.author_id:
        return  # the asker's own follow-up is not a response
    author = session.get(Member, reply.author_id) if reply.author_id else None
    by = "bot" if (author and author.is_bot) or reply.is_automated else "staff" if (author and author.is_staff) else "member"
    if item.first_response_at is None or reply.created_at < item.first_response_at:
        item.first_response_at = reply.created_at
        item.first_response_by = by
    if item.status in UNANSWERED_STATES:
        item.status = "answered"
    item.updated_at = clock.now()
