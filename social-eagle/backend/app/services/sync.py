"""Incremental sync from a CommunityAdapter change feed into the application database.

Properties:
- Idempotent: every record is keyed by (group, upstream_id); duplicate deliveries never double counts.
- Short transactions: one commit per page, cursor saved with the page.
- Out-of-order safe: children whose parent has not arrived are deferred and retried.
- Late-event safe: an older progress event never overrides a newer completion state.
- Failures are recorded as failures (auth_expired / error / partial) — never as an empty community.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock, kv
from ..connectors.base import AuthExpired, Change, CommunityAdapter, ConnectorError
from ..models import (
    Assignment,
    Course,
    Event,
    EventAttendance,
    EventRegistration,
    Group,
    LeaderboardSnapshot,
    Lesson,
    LessonCompletion,
    Member,
    MemberTag,
    Post,
    ProgressEvent,
    Reaction,
    SessionEvent,
    Submission,
    SupportItem,
    SyncDeferred,
    SyncState,
)
from ..timeutil import parse_ts
from . import notify


class Missing(Exception):
    """A dependency (parent record) is not present yet."""


def _ts(v: str | None) -> datetime | None:
    return parse_ts(v) if v else None


class Applier:
    def __init__(self, session: Session, source: str, dataset: str = "synthetic") -> None:
        self.s = session
        self.source = source
        self.dataset = dataset
        self.now = clock.now()
        self._cache: dict[tuple[str, str], int] = {}
        self.counts: dict[str, int] = {}
        self.new_posts: list[int] = []

    # ---- id resolution ------------------------------------------------------------------------
    def _lookup(self, kind: str, upstream: str | None, model: Any, *filters: Any) -> int:
        if upstream is None:
            raise Missing(f"{kind} reference missing")
        key = (kind, upstream)
        if key in self._cache:
            return self._cache[key]
        q = select(model.id).where(model.upstream_id == upstream, *filters)
        rid = self.s.execute(q).scalar_one_or_none()
        if rid is None:
            raise Missing(f"{kind} {upstream} not yet synced")
        self._cache[key] = rid
        return rid

    def group_id(self, up: str) -> int:
        return self._lookup("group", up, Group, Group.source == self.source)

    def member_id(self, group_id: int, up: str | None) -> int:
        return self._lookup(f"member:{group_id}", up, Member, Member.group_id == group_id)

    def member_any(self, up: str) -> int:
        return self._lookup("member*", up, Member)

    def post_id(self, group_id: int, up: str | None) -> int:
        return self._lookup(f"post:{group_id}", up, Post, Post.group_id == group_id)

    def post_any(self, up: str) -> tuple[int, int]:
        p = self.s.execute(select(Post.id, Post.group_id).where(Post.upstream_id == up)).first()
        if p is None:
            raise Missing(f"post {up} not yet synced")
        return p[0], p[1]

    def course_id(self, up: str) -> int:
        return self._lookup("course", up, Course)

    def lesson_id(self, up: str) -> int:
        return self._lookup("lesson", up, Lesson)

    def event_id(self, up: str) -> int:
        return self._lookup("event", up, Event)

    def assignment_id(self, up: str) -> int:
        return self._lookup("assignment", up, Assignment)

    def _get(self, model: Any, **by: Any) -> Any:
        return self.s.execute(select(model).filter_by(**by)).scalar_one_or_none()

    # ---- entity handlers ------------------------------------------------------------------------
    def apply(self, ch: Change) -> None:
        handler = getattr(self, f"_apply_{ch.entity}", None)
        if handler is None:
            raise ConnectorError(f"unknown entity {ch.entity}")
        handler(ch.payload)
        self.counts[ch.entity] = self.counts.get(ch.entity, 0) + 1

    def _apply_group(self, p: dict[str, Any]) -> None:
        g = self._get(Group, source=self.source, upstream_id=p["upstream_id"])
        if g is None:
            self.s.add(Group(upstream_id=p["upstream_id"], name=p["name"], source=self.source,
                             dataset=self.dataset, created_at=self.now))
        else:
            g.name = p["name"]
        self.s.flush()

    def _apply_member(self, p: dict[str, Any]) -> None:
        gid = self.group_id(p["group_id"])
        m = self._get(Member, group_id=gid, upstream_id=p["upstream_id"])
        fields = dict(
            display_name=p["display_name"], email=p.get("email"), role=p.get("role", "member"), tier=p.get("tier"),
            joined_at=_ts(p.get("joined_at")), left_at=_ts(p.get("left_at")), status=p.get("status", "active"),
            is_bot=bool(p.get("is_bot")), is_staff=bool(p.get("is_staff")), rejoin_count=int(p.get("rejoin_count") or 0),
            onboarding_status=p.get("onboarding_status") or "unknown", observed_at=self.now, dataset=self.dataset,
        )
        if m is None:
            m = Member(group_id=gid, upstream_id=p["upstream_id"], first_observed_at=self.now, **fields)
            self.s.add(m)
            self.s.flush()
        else:
            for k, v in fields.items():
                setattr(m, k, v)
        tags = json.loads(p.get("tags") or "[]")
        have = {t.tag for t in m.tags}
        for t in tags:
            if f"source:{t}" not in have:
                m.tags.append(MemberTag(tag=f"source:{t}"))

    def _apply_course(self, p: dict[str, Any]) -> None:
        gid = self.group_id(p["group_id"])
        c = self._get(Course, group_id=gid, upstream_id=p["upstream_id"])
        if c is None:
            self.s.add(Course(group_id=gid, upstream_id=p["upstream_id"], title=p["title"], description=p.get("description"),
                              access_tiers=p["access_tiers"], dataset=self.dataset))
        else:
            c.title, c.description, c.access_tiers = p["title"], p.get("description"), p["access_tiers"]
        self.s.flush()

    def _apply_lesson(self, p: dict[str, Any]) -> None:
        cid = self.course_id(p["course_id"])
        lsn = self._get(Lesson, upstream_id=p["upstream_id"])
        vals = dict(course_id=cid, title=p["title"], module=p.get("module"), position=p["position"],
                    video_minutes=p.get("video_minutes"))
        if lsn is None:
            self.s.add(Lesson(upstream_id=p["upstream_id"], **vals))
        else:
            for k, v in vals.items():
                setattr(lsn, k, v)
        self.s.flush()

    def _apply_assignment(self, p: dict[str, Any]) -> None:
        cid = self.course_id(p["course_id"])
        lid = self.lesson_id(p["lesson_id"]) if p.get("lesson_id") else None
        a = self._get(Assignment, upstream_id=p["upstream_id"])
        if a is None:
            self.s.add(Assignment(upstream_id=p["upstream_id"], course_id=cid, lesson_id=lid, title=p["title"]))
        else:
            a.title, a.lesson_id = p["title"], lid
        self.s.flush()

    def _apply_event(self, p: dict[str, Any]) -> None:
        gid = self.group_id(p["group_id"])
        e = self._get(Event, group_id=gid, upstream_id=p["upstream_id"])
        vals = dict(title=p["title"], description=p.get("description"), starts_at=parse_ts(p["starts_at"]),
                    ends_at=parse_ts(p["ends_at"]), cancelled=bool(p.get("cancelled")), dataset=self.dataset)
        if e is None:
            self.s.add(Event(group_id=gid, upstream_id=p["upstream_id"], **vals))
        else:
            for k, v in vals.items():
                setattr(e, k, v)
        self.s.flush()

    def _apply_post(self, p: dict[str, Any]) -> None:
        gid = self.group_id(p["group_id"])
        author = self.member_id(gid, p.get("author_id")) if p.get("author_id") else None
        parent = self.post_id(gid, p["parent_id"]) if p.get("parent_id") else None
        root = self.post_id(gid, p["root_id"]) if p.get("root_id") else None
        existing = self._get(Post, group_id=gid, upstream_id=p["upstream_id"])
        version = int(p.get("version") or 1)
        if existing is not None:
            # Ignore stale duplicates; apply edits and deletions.
            if version < existing.version and not (p.get("deleted_at") and not existing.deleted_at):
                return
            existing.body = p["body"]
            existing.title = p.get("title")
            existing.edited_at = _ts(p.get("edited_at"))
            existing.deleted_at = _ts(p.get("deleted_at")) or existing.deleted_at
            existing.version = max(version, existing.version)
            existing.observed_at = self.now
            return
        post = Post(group_id=gid, upstream_id=p["upstream_id"], author_id=author, parent_id=parent, root_id=root,
                    kind=p["kind"], title=p.get("title"), body=p["body"], category=p.get("category"),
                    created_at=parse_ts(p["created_at"]), edited_at=_ts(p.get("edited_at")),
                    deleted_at=_ts(p.get("deleted_at")), observed_at=self.now, version=version,
                    is_automated=bool(p.get("is_automated")), client_ref=p.get("client_ref"), dataset=self.dataset)
        self.s.add(post)
        self.s.flush()
        self._cache[(f"post:{gid}", p["upstream_id"])] = post.id
        self.new_posts.append(post.id)
        if post.kind == "post":
            from .support import maybe_open_support_item

            maybe_open_support_item(self.s, post, kv.get(self.s, "thresholds"))
        elif root is not None:
            from .support import record_response

            record_response(self.s, root, post)

    def _apply_reaction(self, p: dict[str, Any]) -> None:
        gid = self.group_id(p["group_id"])
        post = self.post_id(gid, p["post_id"])
        mem = self.member_id(gid, p.get("member_id")) if p.get("member_id") else None
        r = self._get(Reaction, group_id=gid, upstream_id=p["upstream_id"])
        if r is None:
            self.s.add(Reaction(group_id=gid, upstream_id=p["upstream_id"], post_id=post, member_id=mem,
                                kind=p.get("kind", "like"), created_at=parse_ts(p["created_at"]),
                                deleted_at=_ts(p.get("deleted_at")), dataset=self.dataset))
        else:
            r.deleted_at = _ts(p.get("deleted_at"))

    def _apply_progress(self, p: dict[str, Any]) -> None:
        if self._get(ProgressEvent, upstream_id=p["upstream_id"]) is not None:
            return  # duplicate delivery
        mid = self.member_any(p["member_id"])
        lid = self.lesson_id(p["lesson_id"])
        at = parse_ts(p["occurred_at"])
        self.s.add(ProgressEvent(upstream_id=p["upstream_id"], member_id=mid, lesson_id=lid, kind=p["kind"],
                                 occurred_at=at, observed_at=self.now, dataset=self.dataset))
        lc = self._get(LessonCompletion, member_id=mid, lesson_id=lid)
        completed = p["kind"] == "completed"
        if lc is None:
            self.s.add(LessonCompletion(member_id=mid, lesson_id=lid, completed=completed,
                                        completed_at=at if completed else None, state_at=at,
                                        observed_at=self.now, dataset=self.dataset))
        elif lc.state_at is None or at >= lc.state_at:
            lc.completed = completed
            lc.completed_at = at if completed else None
            lc.state_at = at
            lc.observed_at = self.now
        self.s.flush()

    def _apply_submission(self, p: dict[str, Any]) -> None:
        aid = self.assignment_id(p["assignment_id"])
        mid = self.member_any(p["member_id"])
        s = self._get(Submission, upstream_id=p["upstream_id"])
        vals = dict(assignment_id=aid, member_id=mid, status=p["status"], submitted_at=parse_ts(p["submitted_at"]),
                    reviewed_at=_ts(p.get("reviewed_at")), reviewer=p.get("reviewer"), feedback=p.get("feedback"))
        if s is None:
            self.s.add(Submission(upstream_id=p["upstream_id"], **vals))
        else:
            for k, v in vals.items():
                setattr(s, k, v)

    def _apply_registration(self, p: dict[str, Any]) -> None:
        eid = self.event_id(p["event_id"])
        mid = self.member_any(p["member_id"])
        if self._get(EventRegistration, event_id=eid, member_id=mid) is None:
            self.s.add(EventRegistration(upstream_id=p["upstream_id"], event_id=eid, member_id=mid,
                                         registered_at=parse_ts(p["registered_at"])))
            self.s.flush()

    def _apply_attendance(self, p: dict[str, Any]) -> None:
        eid = self.event_id(p["event_id"])
        mid = self.member_any(p["member_id"])
        joined, left = _ts(p.get("joined_at")), _ts(p.get("left_at"))
        dur = round((left - joined).total_seconds() / 60, 1) if joined and left else None
        a = self._get(EventAttendance, event_id=eid, member_id=mid)
        if a is None:
            self.s.add(EventAttendance(upstream_id=p["upstream_id"], event_id=eid, member_id=mid, joined_at=joined,
                                       left_at=left, duration_minutes=dur))
            self.s.flush()
        else:
            a.joined_at, a.left_at, a.duration_minutes = joined, left, dur

    def _apply_leaderboard(self, p: dict[str, Any]) -> None:
        if self._get(LeaderboardSnapshot, upstream_id=p["upstream_id"]) is not None:
            return
        gid = self.group_id(p["group_id"])
        mid = self.member_id(gid, p["member_id"])
        self.s.add(LeaderboardSnapshot(upstream_id=p["upstream_id"], group_id=gid, member_id=mid, points=p["points"],
                                       level=p["level"], snapshot_at=parse_ts(p["snapshot_at"]), dataset=self.dataset))

    def _apply_session(self, p: dict[str, Any]) -> None:
        if self._get(SessionEvent, upstream_id=p["upstream_id"]) is not None:
            return
        mid = self.member_any(p["member_id"])
        self.s.add(SessionEvent(upstream_id=p["upstream_id"], member_id=mid, kind=p["kind"], at=parse_ts(p["at"]),
                                dataset=self.dataset))


def _state(session: Session, source: str) -> SyncState:
    st = session.execute(select(SyncState).filter_by(source=source, resource="feed")).scalar_one_or_none()
    if st is None:
        st = SyncState(source=source, resource="feed", status="never", coverage={})
        session.add(st)
        session.flush()
    return st


def _apply_change(session: Session, ap: Applier, ch: Change, source: str) -> bool:
    """Apply one change in a savepoint. Returns False (and defers it) if a dependency is missing."""
    try:
        with session.begin_nested():
            ap.apply(ch)
        return True
    except Missing as e:
        ap._cache.clear()
        exists = session.execute(
            select(SyncDeferred).filter_by(source=source, entity=ch.entity, upstream_id=ch.upstream_id, seq=ch.seq)
        ).scalar_one_or_none()
        if exists is None:
            session.add(SyncDeferred(source=source, seq=ch.seq, entity=ch.entity, upstream_id=ch.upstream_id,
                                     payload=ch.payload, reason=str(e)[:200], attempts=1, first_seen_at=clock.now()))
        else:
            exists.attempts += 1
        return False


def retry_deferred(session: Session, source: str, ap: Applier) -> int:
    resolved = 0
    for _ in range(3):  # a few passes so chains (reply -> comment -> post) resolve
        rows = session.execute(select(SyncDeferred).filter_by(source=source).order_by(SyncDeferred.seq)).scalars().all()
        progress = False
        for d in rows:
            ch = Change(d.seq, d.entity, d.upstream_id, "upsert", d.payload)
            try:
                with session.begin_nested():
                    ap.apply(ch)
                session.delete(d)
                resolved += 1
                progress = True
            except Missing:
                ap._cache.clear()
                d.attempts += 1
        if not progress:
            break
    return resolved


def sync_once(session: Session, adapter: CommunityAdapter, page_size: int = 500, max_pages: int | None = None) -> dict[str, Any]:
    source = adapter.info.source
    st = _state(session, source)
    st.last_attempt_at = clock.now()
    session.commit()
    ap = Applier(session, source)
    pages = applied = deferred = 0
    cursor = st.cursor
    try:
        while True:
            page = adapter.fetch_changes(cursor, page_size)
            for ch in page.changes:
                if _apply_change(session, ap, ch, source):
                    applied += 1
                else:
                    deferred += 1
            cursor = page.next_cursor
            st.cursor = cursor
            st.items_total = (st.items_total or 0) + len(page.changes)
            session.commit()  # one short transaction per page
            pages += 1
            if not page.has_more or (max_pages and pages >= max_pages):
                break
        resolved = retry_deferred(session, source, ap)
        remaining = session.query(SyncDeferred).filter_by(source=source).count()
        head = adapter.health().get("head_cursor")
        complete = (not page.has_more) and remaining == 0
        st.status = "ok" if complete else "partial"
        st.last_success_at = clock.now()
        st.last_error = None if complete else f"{remaining} change(s) waiting for missing parents" if remaining else "more pages pending"
        st.items_last_run = applied
        st.coverage = {"head_cursor": head, "cursor": cursor, "complete": complete, "deferred": remaining,
                       "entities_last_run": ap.counts, "simulated": adapter.info.simulated}
        session.commit()
        if complete:
            notify.resolve(session, f"sync:{source}")
        return {"ok": True, "status": st.status, "pages": pages, "applied": applied, "deferred": deferred,
                "resolved_deferred": resolved, "remaining_deferred": remaining, "cursor": cursor,
                "new_posts": ap.new_posts}
    except ConnectorError as e:
        session.rollback()
        st = _state(session, source)
        st.status = "auth_expired" if isinstance(e, AuthExpired) else ("partial" if pages else "error")
        st.last_error = f"{e.kind}: {e}"
        st.items_last_run = applied
        st.coverage = {**(st.coverage or {}), "complete": False, "cursor": st.cursor, "failed_after_pages": pages}
        notify.raise_(session, f"sync:{source}", "error",
                      "Community connection problem" if not isinstance(e, AuthExpired) else "Community login expired",
                      f"{e.kind}: {e}. Data shown may be stale; it is not an empty community.")
        session.commit()
        return {"ok": False, "status": st.status, "error": e.kind, "detail": str(e), "pages": pages, "applied": applied}
