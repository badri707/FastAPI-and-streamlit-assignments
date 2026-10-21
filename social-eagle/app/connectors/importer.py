"""Validated JSON import adapter.

The same ingestion path is used for synthetic test fixtures, CSV/JSON imports and
records produced by the public read connector, so all of them get identical
deduplication, versioning and provenance handling.

Rules enforced here:
* Stable source IDs, never display names, identify records.
* Re-importing the same record is a no-op (hash unchanged).
* Changed content creates a ContentVersion; the old text is preserved.
* A record missing from a bundle is NOT treated as deleted. Only explicit
  ``deletions`` / ``removed: true`` reactions confirm removal.
* A failed sync stores a failed SyncRun and ingests nothing.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.config import Mode
from app.provenance import record_hash
from app.timeutil import parse_ts

FORMAT = "social-eagle-import/1"


class _B(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _ts(v: Any) -> datetime | None:
    return parse_ts(v)


class CommunityIn(_B):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9\-]{1,118}$")
    name: str
    source_url: str | None = None
    is_synthetic: bool
    is_company_community: bool = False
    expected_sources: list[str] | None = None
    displayed_member_total: str | None = None
    displayed_online: str | None = None


class MemberIn(_B):
    id: str
    name: str
    role: Literal["member", "staff", "bot", "admin"] = "member"
    joined_at: datetime | None = None
    tags: list[str] | None = None
    _v = field_validator("joined_at", mode="before")(_ts)


class CohortIn(_B):
    key: str
    name: str
    course: str | None = None
    starts_on: datetime | None = None
    ends_on: datetime | None = None
    _v = field_validator("starts_on", "ends_on", mode="before")(_ts)


class PeriodIn(_B):
    member: str
    from_: datetime = Field(alias="from")
    to: datetime | None = None
    _v = field_validator("from_", "to", mode="before")(_ts)
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CohortMembershipIn(PeriodIn):
    cohort: str


class AccessPeriodIn(PeriodIn):
    label: Literal["general", "annual", "vip"]
    status: Literal["active", "cancelled", "expired", "unknown"] = "active"


class EntitlementIn(PeriodIn):
    course: str


class EnrolmentIn(PeriodIn):
    course: str
    cohort: str | None = None


class LessonIn(_B):
    id: str
    title: str
    position: int = 0
    released_at: datetime | None = None
    optional: bool = False
    body: str | None = None
    _v = field_validator("released_at", mode="before")(_ts)


class CourseIn(_B):
    id: str
    title: str
    access_note: str | None = None
    lessons: list[LessonIn] = []


class DeadlineIn(_B):
    cohort: str
    course: str
    lesson: str
    due_at: datetime
    _v = field_validator("due_at", mode="before")(_ts)


class ProgressIn(_B):
    member: str
    course: str
    completed_lesson_ids: list[str] | None = None
    completed_lessons: int | None = None
    total_lessons: int | None = None
    observed_at: datetime | None = None
    _v = field_validator("observed_at", mode="before")(_ts)


class PostIn(_B):
    id: str
    author: str | None
    category: str | None = None
    title: str | None = None
    body: str | None = None
    created_at: datetime | None = None
    is_excerpt: bool = False
    url: str | None = None
    displayed_time: str | None = None
    timestamp_precision: str = "second"
    like_count: int | None = None
    comment_count: int | None = None
    _v = field_validator("created_at", mode="before")(_ts)


class CommentIn(_B):
    id: str
    post: str
    parent: str | None = None
    author: str | None
    body: str | None = None
    created_at: datetime | None = None
    url: str | None = None
    _v = field_validator("created_at", mode="before")(_ts)


class ReactionIn(_B):
    id: str
    actor: str
    target_type: Literal["post", "comment"]
    target: str
    created_at: datetime | None = None
    removed: bool = False
    removed_at: datetime | None = None
    _v = field_validator("created_at", "removed_at", mode="before")(_ts)


class AssignmentIn(_B):
    key: str
    title: str
    cohort: str | None = None
    course: str | None = None
    due_at: datetime | None = None
    category: str | None = None
    _v = field_validator("due_at", mode="before")(_ts)


class SubmissionIn(_B):
    id: str
    assignment: str | None
    member: str
    post: str | None = None
    submitted_at: datetime
    classification: Literal["configured", "manual", "ambiguous"] = "configured"
    _v = field_validator("submitted_at", mode="before")(_ts)


class FeedbackIn(_B):
    id: str
    submission: str
    reviewer: str | None = None
    reviewed_at: datetime | None = None
    delivered_at: datetime | None = None
    channel: str | None = None
    result: str | None = None
    follow_up: str | None = None
    _v = field_validator("reviewed_at", "delivered_at", mode="before")(_ts)


class WinIn(_B):
    post: str
    member: str
    category: str | None = None
    verification: Literal["self_reported", "verified"] = "self_reported"


class QuestionIn(_B):
    id: str
    member: str
    post: str | None = None
    comment: str | None = None
    asked_at: datetime
    text: str | None = None
    state: str = "new"
    assigned_to: str | None = None
    _v = field_validator("asked_at", mode="before")(_ts)

    @field_validator("state")
    @classmethod
    def _state(cls, v: str) -> str:
        if v not in m.QUESTION_STATES:
            raise ValueError(f"unknown question state {v}")
        return v


class SupportEventIn(_B):
    id: str
    question: str
    kind: str
    actor: str | None = None
    at: datetime
    note: str | None = None
    _v = field_validator("at", mode="before")(_ts)

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in m.SUPPORT_EVENT_KINDS:
            raise ValueError(f"unknown support event kind {v}")
        return v


class LeaderEntryIn(_B):
    member: str
    rank: int | None = None
    points: int | None = None


class LeaderboardIn(_B):
    period: Literal["7d", "30d", "all"]
    complete: bool = False
    entries: list[LeaderEntryIn]


class DeletionIn(_B):
    type: Literal["post", "comment"]
    id: str


class CoverageIn(_B):
    start: datetime | None = None
    end: datetime | None = None
    status: Literal["complete", "partial", "unknown"] = "unknown"
    gaps: list[str] = []
    pages: list[str] = []
    _v = field_validator("start", "end", mode="before")(_ts)


class Bundle(_B):
    format: Literal["social-eagle-import/1"]
    community: CommunityIn
    source_name: str
    source_ref: str
    method: Literal["import", "fixture", "public_read"] = "import"
    observed_at: datetime
    status: Literal["success", "partial", "failed"] = "success"
    error: str | None = None
    failed_sources: list[str] = []
    parser_version: str | None = None
    coverage: CoverageIn = CoverageIn()
    members: list[MemberIn] = []
    cohorts: list[CohortIn] = []
    cohort_memberships: list[CohortMembershipIn] = []
    access_periods: list[AccessPeriodIn] = []
    courses: list[CourseIn] = []
    entitlements: list[EntitlementIn] = []
    enrolments: list[EnrolmentIn] = []
    lesson_deadlines: list[DeadlineIn] = []
    progress: list[ProgressIn] = []
    posts: list[PostIn] = []
    comments: list[CommentIn] = []
    reactions: list[ReactionIn] = []
    assignments: list[AssignmentIn] = []
    submissions: list[SubmissionIn] = []
    feedback: list[FeedbackIn] = []
    wins: list[WinIn] = []
    questions: list[QuestionIn] = []
    support_events: list[SupportEventIn] = []
    leaderboard: list[LeaderboardIn] = []
    deletions: list[DeletionIn] = []
    _v = field_validator("observed_at", mode="before")(_ts)


class ImportRejected(ValueError):
    pass


class _Ctx:
    def __init__(self, s: Session, b: Bundle, mode: Mode, run: m.SyncRun, community: m.Community):
        self.s, self.b, self.mode, self.run, self.c = s, b, mode, run, community
        self.members: dict[str, m.Member] = {}
        self.courses: dict[str, m.Course] = {}
        self.cohorts: dict[str, m.Cohort] = {}

    def prov(self, payload: Any, *, observed_at: datetime | None = None, precision: str | None = "second",
             displayed: str | None = None, ref: str | None = None) -> dict:
        return dict(
            source_ref=ref or self.b.source_ref,
            source_mode=self.mode.value,
            source_method=self.b.method,
            field_origin=m.OBSERVED if self.b.method == "public_read" else m.IMPORTED,
            observed_at=observed_at or self.b.observed_at,
            source_tz="UTC",
            timestamp_precision=precision,
            displayed_value=displayed,
            record_hash=record_hash(payload),
            parser_version=self.b.parser_version,
            sync_run_id=self.run.id,
        )

    def member(self, sid: str | None) -> m.Member | None:
        if sid is None:
            return None
        if sid in self.members:
            return self.members[sid]
        mem = self.s.scalar(select(m.Member).where(m.Member.community_id == self.c.id, m.Member.source_member_id == sid))
        if mem is None:
            # Referenced but not described: create a minimal identity (never matched by name).
            mem = m.Member(community_id=self.c.id, source_member_id=sid, display_name=f"(unnamed {sid})",
                           first_observed_at=self.b.observed_at, source_ref=self.b.source_ref)
            self.s.add(mem)
            self.s.flush()
        self.members[sid] = mem
        return mem

    def mid(self, sid: str) -> int:
        mem = self.member(sid)
        assert mem is not None
        return mem.id

    def opt_mid(self, sid: str | None) -> int | None:
        return None if sid is None else self.mid(sid)

    def course(self, sid: str) -> m.Course:
        if sid not in self.courses:
            c = self.s.scalar(select(m.Course).where(m.Course.community_id == self.c.id, m.Course.source_course_id == sid))
            if c is None:
                raise ImportRejected(f"unknown course {sid}")
            self.courses[sid] = c
        return self.courses[sid]

    def cohort(self, key: str) -> m.Cohort:
        if key not in self.cohorts:
            c = self.s.scalar(select(m.Cohort).where(m.Cohort.community_id == self.c.id, m.Cohort.key == key))
            if c is None:
                raise ImportRejected(f"unknown cohort {key}")
            self.cohorts[key] = c
        return self.cohorts[key]


def validate_bundle(data: dict) -> Bundle:
    return Bundle.model_validate(data)


def _check_mode(b: Bundle, mode: Mode) -> None:
    if mode is Mode.PRIVATE:
        from app.config import PrivateModeDisabled
        raise PrivateModeDisabled("private imports are deferred")
    if mode is Mode.TEST and not b.community.is_synthetic:
        raise ImportRejected("test workspace accepts only bundles labelled is_synthetic=true")
    if mode is Mode.PUBLIC:
        if b.community.is_synthetic:
            raise ImportRejected("synthetic data can never enter the public workspace")
        if b.community.is_company_community:
            raise ImportRejected("public mode cannot hold Social Eagle company data; private access is deferred")


def ingest_bundle(s: Session, data: dict | Bundle, mode: Mode, now: datetime) -> m.SyncRun:
    b = data if isinstance(data, Bundle) else validate_bundle(data)
    _check_mode(b, mode)

    c = s.scalar(select(m.Community).where(m.Community.slug == b.community.slug))
    if c is None:
        c = m.Community(slug=b.community.slug, name=b.community.name, source_url=b.community.source_url,
                        is_synthetic=b.community.is_synthetic, is_company_community=b.community.is_company_community,
                        expected_sources=b.community.expected_sources)
        s.add(c)
        s.flush()
    elif c.is_synthetic != b.community.is_synthetic:
        raise ImportRejected("bundle synthetic flag disagrees with stored community")
    if b.community.expected_sources is not None:
        c.expected_sources = b.community.expected_sources
    if b.community.displayed_member_total is not None:
        c.displayed_member_total = b.community.displayed_member_total
        c.displayed_online = b.community.displayed_online
        c.totals_observed_at = b.observed_at

    run = m.SyncRun(community_id=c.id, source_name=b.source_name, mode=mode.value, method=b.method, started_at=now,
                    status="running", coverage_start=b.coverage.start, coverage_end=b.coverage.end,
                    coverage_status=b.coverage.status, pages_captured=b.coverage.pages, known_gaps=b.coverage.gaps,
                    failed_sources=b.failed_sources, parser_version=b.parser_version)
    s.add(run)
    s.flush()

    if b.status == "failed":
        run.status = "failed"
        run.coverage_status = "unknown"
        run.error = b.error or "source reported failure"
        run.finished_at = now
        return run

    ctx = _Ctx(s, b, mode, run, c)
    counts = {"seen": 0, "new": 0, "changed": 0}

    def tally(kind: str) -> None:
        counts["seen"] += 1
        if kind in counts:
            counts[kind] += 1

    _ingest_reference(ctx, tally)
    _ingest_activity(ctx, tally)

    run.records_seen, run.records_new, run.records_changed = counts["seen"], counts["new"], counts["changed"]
    run.status = b.status
    run.finished_at = now
    return run


def _upsert_simple(s: Session, model, where: dict, values: dict, tally) -> Any:
    obj = s.scalar(select(model).filter_by(**where))
    if obj is None:
        obj = model(**where, **values)
        s.add(obj)
        tally("new")
    else:
        changed = False
        for k, v in values.items():
            if k in ("observed_at", "sync_run_id", "record_hash", "source_ref", "parser_version"):
                continue
            if getattr(obj, k) != v:
                setattr(obj, k, v)
                changed = True
        if changed:
            obj_values = {k: v for k, v in values.items() if k in ("record_hash", "sync_run_id", "observed_at")}
            for k, v in obj_values.items():
                setattr(obj, k, v)
            tally("changed")
        else:
            tally("same")
    s.flush()
    return obj


def _ingest_reference(ctx: _Ctx, tally) -> None:
    s, b, c = ctx.s, ctx.b, ctx.c
    for mi in b.members:
        mem = s.scalar(select(m.Member).where(m.Member.community_id == c.id, m.Member.source_member_id == mi.id))
        if mem is None:
            mem = m.Member(community_id=c.id, source_member_id=mi.id, display_name=mi.name, role=mi.role,
                           joined_at=mi.joined_at, first_observed_at=b.observed_at, source_ref=b.source_ref, tags=mi.tags)
            s.add(mem)
            s.flush()
            tally("new")
        else:
            changed = False
            if mem.display_name != mi.name:
                mem.display_name = mi.name  # rename: identity unchanged, alias history kept below
                changed = True
            for attr in ("role", "joined_at", "tags"):
                new = getattr(mi, attr)
                if new is not None and getattr(mem, attr) != new:
                    setattr(mem, attr, new)
                    changed = True
            tally("changed" if changed else "same")
        if not s.scalar(select(m.MemberAlias).where(m.MemberAlias.member_id == mem.id, m.MemberAlias.display_name == mi.name)):
            s.add(m.MemberAlias(member_id=mem.id, display_name=mi.name, first_seen_at=b.observed_at))
        ctx.members[mi.id] = mem

    for ci in b.courses:
        course = _upsert_simple(s, m.Course, {"community_id": c.id, "source_course_id": ci.id},
                                {"title": ci.title, "access_note": ci.access_note}, tally)
        ctx.courses[ci.id] = course
        for li in ci.lessons:
            _upsert_simple(s, m.Lesson, {"course_id": course.id, "source_lesson_id": li.id},
                           {"title": li.title, "position": li.position, "released_at": li.released_at,
                            "optional": li.optional, "body": li.body}, tally)

    for co in b.cohorts:
        ctx.cohorts[co.key] = _upsert_simple(
            s, m.Cohort, {"community_id": c.id, "key": co.key},
            {"name": co.name, "course_id": ctx.course(co.course).id if co.course else None,
             "starts_on": co.starts_on, "ends_on": co.ends_on}, tally)

    for cm in b.cohort_memberships:
        _upsert_simple(s, m.CohortMembership,
                       {"member_id": ctx.mid(cm.member), "cohort_id": ctx.cohort(cm.cohort).id, "valid_from": cm.from_},
                       {"valid_to": cm.to, **ctx.prov(cm.model_dump(mode="json"))}, tally)
    for ap in b.access_periods:
        _upsert_simple(s, m.AccessPeriod,
                       {"member_id": ctx.mid(ap.member), "label": ap.label, "valid_from": ap.from_},
                       {"valid_to": ap.to, "status": ap.status, **ctx.prov(ap.model_dump(mode="json"))}, tally)
    for en in b.entitlements:
        _upsert_simple(s, m.Entitlement,
                       {"member_id": ctx.mid(en.member), "course_id": ctx.course(en.course).id, "valid_from": en.from_},
                       {"valid_to": en.to, **ctx.prov(en.model_dump(mode="json"))}, tally)
    for e in b.enrolments:
        _upsert_simple(s, m.CourseEnrolment,
                       {"member_id": ctx.mid(e.member), "course_id": ctx.course(e.course).id, "enrolled_at": e.from_},
                       {"ended_at": e.to, "cohort_id": ctx.cohort(e.cohort).id if e.cohort else None,
                        **ctx.prov(e.model_dump(mode="json"))}, tally)
    for d in b.lesson_deadlines:
        course = ctx.course(d.course)
        lesson = s.scalar(select(m.Lesson).where(m.Lesson.course_id == course.id, m.Lesson.source_lesson_id == d.lesson))
        if lesson is None:
            raise ImportRejected(f"unknown lesson {d.lesson}")
        _upsert_simple(s, m.LessonDeadline, {"cohort_id": ctx.cohort(d.cohort).id, "lesson_id": lesson.id},
                       {"due_at": d.due_at}, tally)
    for a in b.assignments:
        _upsert_simple(s, m.AssignmentDef, {"community_id": c.id, "key": a.key},
                       {"title": a.title, "cohort_id": ctx.cohort(a.cohort).id if a.cohort else None,
                        "course_id": ctx.course(a.course).id if a.course else None,
                        "due_at": a.due_at, "category_mapping": a.category}, tally)


def _versioned(ctx: _Ctx, model, entity_type: str, where: dict, content: dict, values: dict, tally) -> Any:
    """Insert or update a post/comment, preserving earlier versions when content changes."""
    s = ctx.s
    h = record_hash(content)
    obj = s.scalar(select(model).filter_by(**where))
    if obj is None:
        obj = model(**where, **values, record_hash=h)
        s.add(obj)
        s.flush()
        s.add(m.ContentVersion(entity_type=entity_type, entity_id=obj.id, version=1, title=content.get("title"),
                               excerpt=content.get("body"), record_hash=h, observed_at=ctx.b.observed_at,
                               sync_run_id=ctx.run.id))
        tally("new")
        return obj
    if obj.record_hash != h:
        obj.version += 1
        s.add(m.ContentVersion(entity_type=entity_type, entity_id=obj.id, version=obj.version, title=content.get("title"),
                               excerpt=content.get("body"), record_hash=h, observed_at=ctx.b.observed_at,
                               sync_run_id=ctx.run.id))
        for k, v in values.items():
            if k == "observed_at":
                continue  # keep first observation time; versions record later ones
            setattr(obj, k, v)
        obj.record_hash = h
        tally("changed")
    else:
        # Same content; still refresh displayed counters without creating a version.
        for k in ("displayed_like_count", "displayed_comment_count", "category"):
            if k in values and values[k] is not None:
                setattr(obj, k, values[k])
        tally("same")
    return obj


def _ingest_activity(ctx: _Ctx, tally) -> None:
    s, b, c = ctx.s, ctx.b, ctx.c
    posts: dict[str, m.Post | None] = {}

    def post_by_sid(sid: str) -> m.Post | None:
        if sid not in posts:
            posts[sid] = s.scalar(select(m.Post).where(m.Post.community_id == c.id, m.Post.source_post_id == sid))
        return posts[sid]

    for p in b.posts:
        # Category is classification metadata, not authored text: changing it is not an "edit".
        content = {"title": p.title, "body": p.body}
        prov = ctx.prov(content, precision=p.timestamp_precision, displayed=p.displayed_time, ref=p.url)
        prov.pop("record_hash")
        posts[p.id] = _versioned(ctx, m.Post, "post", {"community_id": c.id, "source_post_id": p.id}, content,
                                 {"author_id": ctx.opt_mid(p.author), "category": p.category,
                                  "title": p.title, "excerpt": p.body, "is_excerpt": p.is_excerpt,
                                  "created_at": p.created_at, "displayed_like_count": p.like_count,
                                  "displayed_comment_count": p.comment_count, **prov}, tally)

    comments: dict[str, m.Comment | None] = {}
    for cmt in sorted(b.comments, key=lambda x: (x.parent is not None,)):
        post = post_by_sid(cmt.post)
        if post is None:
            raise ImportRejected(f"comment {cmt.id} references unknown post {cmt.post}")
        parent = None
        if cmt.parent:
            parent = comments.get(cmt.parent) or s.scalar(
                select(m.Comment).where(m.Comment.community_id == c.id, m.Comment.source_comment_id == cmt.parent))
        content = {"body": cmt.body}
        prov = ctx.prov(content, ref=cmt.url)
        prov.pop("record_hash")
        comments[cmt.id] = _versioned(ctx, m.Comment, "comment", {"community_id": c.id, "source_comment_id": cmt.id},
                                      content, {"post_id": post.id, "parent_comment_id": parent.id if parent else None,
                                                "author_id": ctx.opt_mid(cmt.author),
                                                "excerpt": cmt.body, "created_at": cmt.created_at, **prov}, tally)

    for r in b.reactions:
        tgt: m.Post | m.Comment | None
        if r.target_type == "post":
            tgt = post_by_sid(r.target)
        else:
            tgt = comments.get(r.target) or s.scalar(
                select(m.Comment).where(m.Comment.community_id == c.id, m.Comment.source_comment_id == r.target))
        target_author = tgt.author_id if tgt is not None else None
        existing = s.scalar(select(m.Reaction).where(m.Reaction.community_id == c.id, m.Reaction.source_reaction_id == r.id))
        removed_at = (r.removed_at or b.observed_at) if r.removed else None
        if existing is None:
            s.add(m.Reaction(community_id=c.id, source_reaction_id=r.id, actor_id=ctx.mid(r.actor),
                             target_type=r.target_type, target_source_id=r.target, target_author_id=target_author,
                             created_at=r.created_at, removed_confirmed_at=removed_at,
                             **ctx.prov(r.model_dump(mode="json"))))
            tally("new")
        elif r.removed and existing.removed_confirmed_at is None:
            existing.removed_confirmed_at = removed_at
            tally("changed")
        else:
            tally("same")
        s.flush()

    for d in b.deletions:
        obj: m.Post | m.Comment | None
        if d.type == "post":
            obj = s.scalar(select(m.Post).where(m.Post.community_id == c.id, m.Post.source_post_id == d.id))
        else:
            obj = s.scalar(select(m.Comment).where(m.Comment.community_id == c.id, m.Comment.source_comment_id == d.id))
        if obj is not None and obj.deleted_confirmed_at is None:
            obj.deleted_confirmed_at = b.observed_at
            tally("changed")

    for pr in b.progress:
        course = ctx.course(pr.course)
        obs = pr.observed_at or b.observed_at
        completed = pr.completed_lessons if pr.completed_lesson_ids is None else len(pr.completed_lesson_ids)
        lesson_ids = sorted(
            s.scalars(select(m.Lesson.source_lesson_id).where(m.Lesson.course_id == course.id)).all())
        _upsert_simple(s, m.ProgressSnapshot,
                       {"member_id": ctx.mid(pr.member), "course_id": course.id, "observed_at": obs},
                       {"completed_lessons": completed, "total_lessons": pr.total_lessons,
                        "completed_lesson_ids": sorted(pr.completed_lesson_ids) if pr.completed_lesson_ids is not None else None,
                        "lesson_set_hash": record_hash(lesson_ids),
                        **{k: v for k, v in ctx.prov(pr.model_dump(mode="json"), observed_at=obs).items() if k != "observed_at"}},
                       tally)

    for sub in b.submissions:
        a = s.scalar(select(m.AssignmentDef).where(m.AssignmentDef.community_id == c.id, m.AssignmentDef.key == sub.assignment)) if sub.assignment else None
        post = post_by_sid(sub.post) if sub.post else None
        _upsert_simple(s, m.Submission, {"source_submission_id": f"{c.id}:{sub.id}"},
                       {"assignment_id": a.id if a else None, "member_id": ctx.mid(sub.member),
                        "post_id": post.id if post else None, "submitted_at": sub.submitted_at,
                        "classification": sub.classification, **ctx.prov(sub.model_dump(mode="json"))}, tally)
    for fb in b.feedback:
        sub = s.scalar(select(m.Submission).where(m.Submission.source_submission_id == f"{c.id}:{fb.submission}"))
        if sub is None:
            raise ImportRejected(f"feedback {fb.id} references unknown submission")
        _upsert_simple(s, m.Feedback, {"source_feedback_id": f"{c.id}:{fb.id}"},
                       {"submission_id": sub.id, "reviewer_id": ctx.opt_mid(fb.reviewer),
                        "reviewed_at": fb.reviewed_at, "feedback_delivered_at": fb.delivered_at,
                        "feedback_channel": fb.channel, "assessment_result": fb.result, "follow_up": fb.follow_up,
                        **ctx.prov(fb.model_dump(mode="json"))}, tally)
    for w in b.wins:
        post = post_by_sid(w.post)
        if post is None:
            raise ImportRejected(f"win references unknown post {w.post}")
        _upsert_simple(s, m.Win, {"post_id": post.id},
                       {"member_id": ctx.mid(w.member), "category": w.category,
                        "recorded_at": post.created_at or b.observed_at, "verification": w.verification,
                        **ctx.prov(w.model_dump(mode="json"))}, tally)
    for q in b.questions:
        post = post_by_sid(q.post) if q.post else None
        cm_ = s.scalar(select(m.Comment).where(m.Comment.community_id == c.id, m.Comment.source_comment_id == q.comment)) if q.comment else None
        _upsert_simple(s, m.SupportQuestion, {"community_id": c.id, "source_question_id": q.id},
                       {"member_id": ctx.mid(q.member), "post_id": post.id if post else None,
                        "comment_id": cm_.id if cm_ else None, "asked_at": q.asked_at, "text": q.text, "state": q.state,
                        "assigned_to_id": ctx.opt_mid(q.assigned_to),
                        **ctx.prov(q.model_dump(mode="json"))}, tally)
    for ev in b.support_events:
        q = s.scalar(select(m.SupportQuestion).where(m.SupportQuestion.community_id == c.id,
                                                     m.SupportQuestion.source_question_id == ev.question))
        if q is None:
            raise ImportRejected(f"support event {ev.id} references unknown question")
        _upsert_simple(s, m.SupportEvent, {"source_event_id": f"{c.id}:{ev.id}"},
                       {"question_id": q.id, "kind": ev.kind, "actor_id": ctx.opt_mid(ev.actor),
                        "at": ev.at, "note": ev.note, **ctx.prov(ev.model_dump(mode="json"))}, tally)
    for lb in b.leaderboard:
        snap = m.LeaderboardSnapshot(community_id=c.id, period=lb.period, is_complete=lb.complete,
                                     **ctx.prov(lb.model_dump(mode="json")))
        for e in lb.entries:
            snap.entries.append(m.LeaderboardEntry(member_id=ctx.mid(e.member), rank=e.rank, points=e.points))
        dup = s.scalar(select(m.LeaderboardSnapshot).where(
            m.LeaderboardSnapshot.community_id == c.id, m.LeaderboardSnapshot.period == lb.period,
            m.LeaderboardSnapshot.observed_at == b.observed_at))
        if dup is None:
            s.add(snap)
            tally("new")
        else:
            tally("same")
    s.flush()
