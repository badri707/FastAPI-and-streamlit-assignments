"""Local community simulator (TEST workspace only).

Lets an admin act as a fictional member or staff and post, comment, like, resolve or reopen.
Every action is written through the normal validated importer as a small ``local_sim`` bundle,
so it gets the same provenance, dedupe, versioning and coverage records as real data.
Nothing here ever contacts Skool.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models as m
from app.config import Mode
from app.connectors.importer import ingest_bundle
from app.timeutil import iso, local_date_of, local_day_bounds_utc

QUESTION_CATEGORIES = {"Questions", "Help", "Doubts"}
WIN_CATEGORIES = {"Wins"}
_Q_WORDS = re.compile(r"\?|^(how|what|why|where|when|which|can|could|should|is|are|do|does|anyone)\b", re.I)


class SimulatorError(ValueError):
    pass


def require_test_community(c: m.Community | None) -> m.Community:
    if c is None or not c.is_synthetic:
        raise SimulatorError("The community simulator works only on the synthetic test workspace.")
    return c


def member_by_sid(s: Session, c: m.Community, sid: str) -> m.Member:
    mem = s.scalar(select(m.Member).where(m.Member.community_id == c.id, m.Member.source_member_id == sid))
    if mem is None:
        raise SimulatorError(f"unknown member {sid}")
    return mem


def looks_like_question(text: str) -> bool:
    return bool(_Q_WORDS.search(text.strip()))


def _coverage_start(s: Session, c: m.Community, now: datetime) -> datetime:
    """The simulator is the complete source for this synthetic community from the start of today
    (or from the end of the last complete capture, if later). Earlier gaps stay gaps."""
    today_start, _ = local_day_bounds_utc(local_date_of(now))
    prev_end = s.scalar(select(func.max(m.SyncRun.coverage_end)).where(
        m.SyncRun.community_id == c.id, m.SyncRun.source_name == "discussions", m.SyncRun.status == "success",
        m.SyncRun.coverage_status == "complete"))
    if prev_end is None or prev_end < today_start:
        return today_start
    return min(prev_end, now)


def _ingest(s: Session, c: m.Community, now: datetime, **records) -> m.SyncRun:
    bundle = {
        "format": "social-eagle-import/1",
        "community": {"slug": c.slug, "name": c.name, "is_synthetic": True,
                      "is_company_community": c.is_company_community},
        "source_name": "discussions", "source_ref": f"local-sim://{c.slug}", "method": "local_sim",
        "observed_at": iso(now), "parser_version": "local-sim-1",
        "coverage": {"start": iso(_coverage_start(s, c, now)), "end": iso(now), "status": "complete"},
        **records,
    }
    return ingest_bundle(s, bundle, Mode.TEST, now)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _open_question_for_post(s: Session, post: m.Post) -> m.SupportQuestion | None:
    return s.scalar(select(m.SupportQuestion).where(m.SupportQuestion.post_id == post.id,
                                                    m.SupportQuestion.comment_id.is_(None),
                                                    m.SupportQuestion.state != "closed"))


def create_post(s: Session, c: m.Community, author_sid: str, category: str, title: str, body: str,
                now: datetime) -> m.Post:
    require_test_community(c)
    author = member_by_sid(s, c, author_sid)
    title, body = title.strip()[:300], body.strip()[:5000]
    if not title:
        raise SimulatorError("title is required")
    pid = _new_id("sim-p")
    records: dict = {"posts": [{"id": pid, "author": author_sid, "category": category or "General", "title": title,
                                "body": body, "created_at": iso(now), "url": f"/test/thread/{pid}"}]}
    if author.role == "member":
        if category in QUESTION_CATEGORIES or looks_like_question(title):
            records["questions"] = [{"id": f"q-{pid}", "member": author_sid, "post": pid, "asked_at": iso(now),
                                     "text": f"{title}\n{body}".strip()}]
        if category in WIN_CATEGORIES:
            records["wins"] = [{"post": pid, "member": author_sid}]
        sub = _submission_for(s, c, author, category, pid, now)
        if sub:
            records["submissions"] = [sub]
    _ingest(s, c, now, **records)
    q = s.scalar(select(m.SupportQuestion).where(m.SupportQuestion.source_question_id == f"q-{pid}"))
    if q is not None:
        q.classification_origin = "rule_based"
        q.next_action = "Bot to research and respond"
    post = s.scalar(select(m.Post).where(m.Post.community_id == c.id, m.Post.source_post_id == pid))
    assert post is not None
    return post


def _submission_for(s: Session, c: m.Community, author: m.Member, category: str, pid: str, now: datetime) -> dict | None:
    """Only configured category mappings create submissions; if the mapping is ambiguous it is flagged."""
    defs = s.scalars(select(m.AssignmentDef).where(m.AssignmentDef.community_id == c.id,
                                                   m.AssignmentDef.category_mapping == category)).all()
    if not defs:
        return None
    current = set(s.scalars(select(m.CohortMembership.cohort_id).where(
        m.CohortMembership.member_id == author.id, m.CohortMembership.valid_from <= now,
        (m.CohortMembership.valid_to.is_(None)) | (m.CohortMembership.valid_to > now))))
    matches = [d for d in defs if d.cohort_id in current]
    base = {"id": f"sub-{pid}", "member": author.source_member_id, "post": pid, "submitted_at": iso(now)}
    if len(matches) == 1:
        return {**base, "assignment": matches[0].key, "classification": "configured"}
    return {**base, "assignment": None, "classification": "ambiguous"}


def create_comment(s: Session, c: m.Community, author_sid: str, post_id: int, body: str, now: datetime,
                   parent_comment_id: int | None = None, event_kind: str | None = None,
                   event_note: str | None = None) -> m.Comment:
    """Add a comment. Support events are derived from who replied:
    staff → staff_response, the asker → member_reply, another learner → peer_response.
    ``event_kind`` lets the bot record bot_response / clarification_request explicitly."""
    require_test_community(c)
    author = member_by_sid(s, c, author_sid)
    post = s.get(m.Post, post_id)
    if post is None or post.community_id != c.id:
        raise SimulatorError("unknown post")
    body = body.strip()[:5000]
    if not body:
        raise SimulatorError("comment is empty")
    parent_sid = None
    if parent_comment_id:
        parent = s.get(m.Comment, parent_comment_id)
        parent_sid = parent.source_comment_id if parent else None
    cid = _new_id("sim-c")
    records: dict = {"comments": [{"id": cid, "post": post.source_post_id, "parent": parent_sid, "author": author_sid,
                                   "body": body, "created_at": iso(now),
                                   "url": f"/test/thread/{post.source_post_id}#{cid}"}]}
    q = None
    if parent_comment_id:  # replying under a comment-level question
        q = s.scalar(select(m.SupportQuestion).where(m.SupportQuestion.comment_id == parent_comment_id,
                                                     m.SupportQuestion.state != "closed"))
    if q is None:
        q = _open_question_for_post(s, post)
    if q is not None:
        kind = event_kind
        if kind is None:
            if author.role in ("staff", "admin"):
                kind = "staff_response"
            elif author.id == q.member_id:
                kind = "member_reply"
            elif author.role == "member":
                kind = "peer_response"
        if kind:
            records["support_events"] = [{"id": f"ev-{cid}", "question": q.source_question_id, "kind": kind,
                                          "actor": author_sid, "at": iso(now), "note": event_note}]
    elif author.role == "member" and post.author_id != author.id and looks_like_question(body):
        records["questions"] = [{"id": f"q-{cid}", "member": author_sid, "post": post.source_post_id,
                                 "comment": cid, "asked_at": iso(now), "text": body}]
    # questions referencing the comment need it ingested first
    if "questions" in records:
        qrec = records.pop("questions")
        _ingest(s, c, now, **records)
        _ingest(s, c, now, questions=qrec)
        newq = s.scalar(select(m.SupportQuestion).where(m.SupportQuestion.source_question_id == qrec[0]["id"]))
        if newq:
            newq.classification_origin = "rule_based"
            newq.next_action = "Bot to research and respond"
    else:
        _ingest(s, c, now, **records)
    if q is not None and records.get("support_events"):
        kind = records["support_events"][0]["kind"]
        if kind == "staff_response":
            q.state, q.last_action, q.next_action = "answered", f"Staff replied ({author.display_name})", \
                "Wait for member confirmation"
        elif kind == "member_reply" and q.state == "awaiting_member":
            q.last_action, q.next_action = "Member replied to clarification", "Bot to resume"
    cm = s.scalar(select(m.Comment).where(m.Comment.community_id == c.id, m.Comment.source_comment_id == cid))
    assert cm is not None
    return cm


def like(s: Session, c: m.Community, actor_sid: str, target_type: str, target_id: int, now: datetime) -> None:
    require_test_community(c)
    member_by_sid(s, c, actor_sid)
    if target_type == "post":
        tgt = s.get(m.Post, target_id)
        tsid = tgt.source_post_id if tgt else None
    else:
        tgtc = s.get(m.Comment, target_id)
        tsid = tgtc.source_comment_id if tgtc else None
    if tsid is None:
        raise SimulatorError("unknown like target")
    # one like per actor per target (stable id) — repeated clicks are idempotent
    _ingest(s, c, now, reactions=[{"id": f"like-{actor_sid}-{target_type}-{tsid}", "actor": actor_sid,
                                   "target_type": target_type, "target": tsid, "created_at": iso(now)}])


def record_event(s: Session, c: m.Community, q: m.SupportQuestion, kind: str, actor_sid: str | None, now: datetime,
                 note: str | None = None) -> None:
    _ingest(s, c, now, support_events=[{"id": _new_id("ev"), "question": q.source_question_id, "kind": kind,
                                        "actor": actor_sid, "at": iso(now), "note": note}])


def confirm_resolved(s: Session, c: m.Community, q: m.SupportQuestion, now: datetime) -> None:
    asker = s.get(m.Member, q.member_id)
    assert asker is not None
    record_event(s, c, q, "resolution_confirmed", asker.source_member_id, now, "Member confirmed it is solved")
    q.state, q.last_action, q.next_action = "closed", "Member confirmed resolution", None
    q.closed_reason = "resolved (member confirmed)"


def reopen(s: Session, c: m.Community, q: m.SupportQuestion, now: datetime, note: str = "Member says not solved") -> None:
    asker = s.get(m.Member, q.member_id)
    assert asker is not None
    record_event(s, c, q, "reopened", asker.source_member_id, now, note)
    q.state, q.last_action, q.next_action, q.closed_reason = "new", "Reopened by member", "Bot to re-check", None


def extend_live_coverage(s: Session, c: m.Community, now: datetime) -> bool:
    """While the worker runs, the local simulator is the complete record of activity for this
    synthetic community, so the latest local_sim capture is extended up to ``now``. This never
    happens for real sources, whose coverage only comes from actual captures."""
    if not c.is_synthetic:
        return False
    last = s.scalar(select(m.SyncRun).where(m.SyncRun.community_id == c.id, m.SyncRun.source_name == "discussions")
                    .order_by(m.SyncRun.id.desc()))
    if last is None or last.method != "local_sim" or last.status != "success" or last.coverage_end is None:
        return False
    if last.coverage_end < now:
        last.coverage_end = now
        last.finished_at = now
        return True
    return False
