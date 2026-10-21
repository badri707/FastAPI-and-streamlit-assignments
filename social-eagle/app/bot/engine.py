"""Question-handling engine (spec section 7A), TEST workspace only.

For each captured question the engine decides, in this order:
1. Explicit request for a human, or a topic needing the owner's authority
   (refunds, payments, deadline extensions, exceptions, complaints) → escalate to owner.
2. Too vague to research → ask the member ONE clarification, then resume on their reply.
3. Retrieve permission-scoped course lessons and owner-approved answers.
   Enough evidence → post an answer that cites its sources (local thread only).
   Not enough → escalate, saying exactly what was checked and what is missing.

An answer is never treated as resolution: the member (or staff) must confirm. A reopened
question that the bot already answered goes to the owner instead of looping.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import models as m
from app.bot import community as sim
from app.bot.ai import ExtractiveProvider, Passage, Provider, select_provider
from app.retrieval import rebuild_index
from app.timeutil import iso, sql_ts

OWNER_TOPICS = [
    (re.compile(r"\b(refund|money back|chargeback)\b", re.I), "refund request — needs owner decision"),
    (re.compile(r"\b(payment|invoice|billing|charged|subscription|cancel\w*)\b", re.I), "billing/subscription matter"),
    (re.compile(r"\b(extension|extend\w*|more time|late submission)\b", re.I), "deadline exception request"),
    (re.compile(r"\b(exception|special case|discount|scholarship)\b", re.I), "exception/commercial decision"),
    (re.compile(r"\b(complain\w*|unhappy|disappointed|nobody (helped|replied|answered))\b", re.I),
     "complaint — needs a human response"),
]
HUMAN_REQUEST = re.compile(r"\b(talk|speak|chat|call)\b.{0,15}\b(human|person|coach|mentor|someone|staff|team)\b|"
                           r"\breal (person|human)\b", re.I)
STOP = set("""a an the and or but if of to in on at for with from by is are was were be been am i me my we our you your
it its this that these those how what why where when which who can could should would do does did have has had
please help anyone know any some there here about into just get got need want tell thanks thank hi hello hey""".split())
MAX_CLARIFICATIONS = 1
MAX_BOT_ANSWERS = 1
BOT_DISCLOSURE = "\n\n— EagleBot (automated assistant, test workspace). Not solved? Reply here or ask for a coach."


def content_words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) >= 3 and w not in STOP}


@dataclass
class Outcome:
    question_id: int
    action: str  # answered | clarification | escalated | skipped
    detail: str


def _state(s: Session, key: str) -> str | None:
    row = s.get(m.AppState, key)
    return row.value if row else None


def bot_enabled_since(s: Session, c: m.Community, now: datetime) -> datetime:
    key = f"bot:enabled_since:{c.slug}"
    v = _state(s, key)
    if v is None:
        s.add(m.AppState(key=key, value=iso(now)))
        return now
    return datetime.fromisoformat(v.replace("Z", ""))


def _bot_member(s: Session, c: m.Community) -> m.Member:
    bot = s.scalar(select(m.Member).where(m.Member.community_id == c.id, m.Member.role == "bot").order_by(m.Member.id))
    if bot is None:
        raise sim.SimulatorError("no bot member configured in this community")
    return bot


def retrieve(s: Session, c: m.Community, q: m.SupportQuestion, query: str, now: datetime) -> list[tuple[float, Passage]]:
    """Permission-scoped lessons + approved knowledge, scored by content-word overlap with the question."""
    words = content_words(query)
    if not words:
        return []
    rebuild_index(s)
    fts = " OR ".join(f'"{w}"' for w in sorted(words)[:12])
    rows = s.execute(text(
        "SELECT CAST(f.lesson_id AS INTEGER) AS lid FROM lesson_fts f "
        "JOIN courses c ON c.id = CAST(f.course_id AS INTEGER) "
        "WHERE lesson_fts MATCH :q AND c.community_id = :cid AND CAST(f.course_id AS INTEGER) IN "
        "(SELECT course_id FROM entitlements WHERE member_id = :mid AND valid_from <= :at "
        " AND (valid_to IS NULL OR valid_to > :at)) ORDER BY rank LIMIT 6"),
        {"q": fts, "cid": c.id, "mid": q.member_id, "at": sql_ts(now)}).all()
    out: list[tuple[float, Passage]] = []
    for r in rows:
        lsn = s.get(m.Lesson, r.lid)
        if lsn is None or not lsn.body:
            continue
        course = s.get(m.Course, lsn.course_id)
        score = len(words & content_words(f"{lsn.title} {lsn.body}")) / len(words)
        out.append((score, Passage(f"lesson:{lsn.id}", f"{course.title if course else ''} › {lsn.title}", lsn.body,
                                   f"/lessons/{lsn.id}")))
    entitled = set(s.scalars(select(m.Entitlement.course_id).where(
        m.Entitlement.member_id == q.member_id, m.Entitlement.valid_from <= now,
        (m.Entitlement.valid_to.is_(None)) | (m.Entitlement.valid_to > now))))
    for k in s.scalars(select(m.KnowledgeItem).where(m.KnowledgeItem.community_id == c.id, m.KnowledgeItem.active)):
        if k.course_id is not None and k.course_id not in entitled:
            continue
        score = len(words & content_words(f"{k.question} {k.answer}")) / len(words)
        if score > 0:
            out.append((score, Passage(f"knowledge:{k.id}", f"Approved answer: {k.question[:80]}", k.answer,
                                       f"/bot#knowledge-{k.id}")))
    out.sort(key=lambda t: -t[0])
    return out


def _escalate(s: Session, c: m.Community, q: m.SupportQuestion, now: datetime, reason: str, checked: str,
              proposed: str | None = None, acknowledge: bool = True) -> Outcome:
    bot = _bot_member(s, c)
    q.state, q.escalation_reason, q.proposed_answer = "awaiting_owner", f"{reason}. Checked: {checked}", proposed
    q.last_action, q.next_action = "Escalated to owner", "Owner to answer, assign, defer or close"
    sim.record_event(s, c, q, "escalated", bot.source_member_id, now, reason)
    if acknowledge and q.post_id:
        sim.create_comment(s, c, bot.source_member_id, q.post_id,
                           "Thanks — I've passed this to the Social Eagle team so a person can help." + BOT_DISCLOSURE,
                           now, parent_comment_id=q.comment_id, event_kind="bot_response",
                           event_note="acknowledgement only — not an answer")
    member = s.get(m.Member, q.member_id)
    n_events = len(s.scalars(select(m.SupportEvent.id).where(m.SupportEvent.question_id == q.id)).all())
    key = f"escalation:{c.slug}:{q.id}:{n_events}"
    if not s.scalar(select(m.OutboxMessage).where(m.OutboxMessage.dedupe_key == key)):
        s.add(m.OutboxMessage(dedupe_key=key, channel="in_app", recipient="owner", created_at=now,
                              subject=f"Needs owner: {member.display_name if member else '?'} — {(q.text or '')[:70]}"))
    return Outcome(q.id, "escalated", reason)


def handle_question(s: Session, c: m.Community, q: m.SupportQuestion, now: datetime,
                    provider: Provider | None = None) -> Outcome:
    events = s.scalars(select(m.SupportEvent).where(m.SupportEvent.question_id == q.id).order_by(m.SupportEvent.at)).all()
    clar = [e for e in events if e.kind == "clarification_request"]
    replies = [e for e in events if e.kind == "member_reply" and (not clar or e.at >= clar[-1].at)]
    if q.state == "awaiting_member":
        if not replies:
            return Outcome(q.id, "skipped", "waiting for the member's clarification")
    elif q.state != "new":
        return Outcome(q.id, "skipped", f"state {q.state}")
    q.state, q.last_action = "researching", "Bot researching"
    # Build the full question text, including the member's clarification replies.
    reply_text = []
    for e in replies:
        cm = s.scalar(select(m.Comment).where(m.Comment.source_comment_id == e.source_event_id.split(":", 1)[-1][3:]))
        if cm and cm.excerpt:
            reply_text.append(cm.excerpt)
    query = " ".join([q.text or "", *reply_text])
    reopened = any(e.kind == "reopened" for e in events)

    if HUMAN_REQUEST.search(query):
        return _escalate(s, c, q, now, "member explicitly asked for a human", "no research needed")
    for rx, reason in OWNER_TOPICS:
        if rx.search(query):
            return _escalate(s, c, q, now, reason, "topic requires owner authority; bot does not decide it")
    if reopened and q.bot_attempts >= MAX_BOT_ANSWERS:
        return _escalate(s, c, q, now, "member reopened after the bot's answer", "previous bot answer did not resolve it")

    passages = retrieve(s, c, q, query, now)
    good = [p for score, p in passages if score >= 0.5]
    words = content_words(query)
    if len(words) < 2 and not good:
        if q.clarifications_sent >= MAX_CLARIFICATIONS:
            return _escalate(s, c, q, now, "still unclear after one clarification", "lessons and approved answers")
        bot = _bot_member(s, c)
        q.clarifications_sent += 1
        q.state, q.last_action, q.next_action = "awaiting_member", "Asked member to clarify", "Resume when member replies"
        if q.post_id:
            sim.create_comment(s, c, bot.source_member_id, q.post_id,
                               "Could you share a bit more detail — which lesson or step are you on, and what "
                               "happened when you tried it?" + BOT_DISCLOSURE, now,
                               parent_comment_id=q.comment_id, event_kind="clarification_request")
        return Outcome(q.id, "clarification", "asked one clarifying question")

    checked = f"{len(passages)} permitted passages searched; best overlap " + (
        f"{passages[0][0]:.0%}" if passages else "none")
    if not good:
        return _escalate(s, c, q, now, "no approved material covers this question", checked)

    provider = provider or select_provider()
    draft = provider.answer(query, good[:4])
    if draft is None or not draft.sufficient:
        if not isinstance(provider, ExtractiveProvider):
            fallback = ExtractiveProvider().answer(query, good[:4])
            proposed = fallback.text if fallback else None
        else:
            proposed = None
        return _escalate(s, c, q, now, f"answer generator ({provider.name}) judged the evidence insufficient", checked,
                         proposed)
    cites = "\n".join(f"Source: {p.title} ({p.link})" for p in draft.used)
    label = "" if draft.origin == "extractive" else f"\n(Written by local AI model {draft.origin[3:]} from the sources above.)"
    bot = _bot_member(s, c)
    body = f"{draft.text}\n\n{cites}{label}{BOT_DISCLOSURE}"
    comment = sim.create_comment(s, c, bot.source_member_id, q.post_id, body, now, parent_comment_id=q.comment_id,
                                 event_kind="bot_response", event_note=f"answer via {draft.origin}") if q.post_id else None
    q.bot_attempts += 1
    verified = comment is not None and s.get(m.Comment, comment.id) is not None
    q.state = "answered"
    q.last_action = f"Bot answered via {draft.origin}" + (" (posted and verified in local thread)" if verified else "")
    q.next_action = "Wait for member to confirm it is solved (an answer is not resolution)"
    return Outcome(q.id, "answered", draft.origin)


def process_pending(s: Session, c: m.Community, now: datetime, provider: Provider | None = None,
                    include_backlog: bool = False) -> list[Outcome]:
    """Handle new questions and clarification replies. Only questions captured after the bot was
    switched on are handled automatically; older backlog needs an explicit request."""
    sim.require_test_community(c)
    pause = s.get(m.AppState, "paused")
    if pause is not None and pause.value == "1":
        return []
    since = bot_enabled_since(s, c, now)
    stmt = select(m.SupportQuestion).where(m.SupportQuestion.community_id == c.id,
                                           m.SupportQuestion.state.in_(("new", "awaiting_member")))
    if not include_backlog:
        stmt = stmt.where(m.SupportQuestion.asked_at >= since)
    out = []
    for q in s.scalars(stmt.order_by(m.SupportQuestion.asked_at)).all():
        out.append(handle_question(s, c, q, now, provider))
    return out


# ---------------------------------------------------------------- owner actions

def owner_answer(s: Session, c: m.Community, q: m.SupportQuestion, staff_sid: str, answer: str, now: datetime,
                 save_as_knowledge: bool = False, approved_by: str = "owner") -> None:
    staff = sim.member_by_sid(s, c, staff_sid)
    if staff.role not in ("staff", "admin"):
        raise sim.SimulatorError("owner answers must be posted by a staff/admin member")
    if q.post_id is None:
        raise sim.SimulatorError("question has no thread")
    sim.create_comment(s, c, staff_sid, q.post_id, answer, now, parent_comment_id=q.comment_id)
    q.state, q.last_action = "answered", f"Owner answer posted by {staff.display_name} (verified in local thread)"
    q.next_action = "Wait for member to confirm it is solved"
    if save_as_knowledge:
        s.add(m.KnowledgeItem(community_id=c.id, question=q.text or "", answer=answer, approved_by=approved_by,
                              approved_at=now, from_question_id=q.id))


def owner_close(s: Session, c: m.Community, q: m.SupportQuestion, reason: str, now: datetime) -> None:
    sim.record_event(s, c, q, "closed", None, now, reason)
    q.state, q.closed_reason, q.last_action, q.next_action = "closed", reason, f"Closed by owner: {reason}", None


def owner_assign(s: Session, c: m.Community, q: m.SupportQuestion, staff_sid: str, now: datetime) -> None:
    staff = sim.member_by_sid(s, c, staff_sid)
    sim.record_event(s, c, q, "assigned", staff_sid, now)
    q.assigned_to_id = staff.id
    q.last_action, q.next_action = f"Assigned to {staff.display_name}", f"{staff.display_name} to reply"


def register_counts(s: Session, c: m.Community) -> dict[str, int]:
    rows = s.execute(select(m.SupportQuestion.state, text("count(*)")).where(m.SupportQuestion.community_id == c.id)
                     .group_by(m.SupportQuestion.state)).all()
    return {st: n for st, n in rows}
