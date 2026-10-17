"""Application data model.

Conventions:
- All timestamps are naive UTC.
- `upstream_id` is the stable source identifier, unique within a group. Display names are never identities.
- `dataset` labels provenance: "synthetic" (seeded evaluation data) or "import:<batch_id>" (optional user import).
- `source_ts` is when the event happened at the source; `observed_at` is when this application saw it.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    upstream_id: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(40))  # simulator | import | skool (future)
    dataset: Mapped[str] = mapped_column(String(60), default="synthetic")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("source", "upstream_id", name="uq_group_source_upstream"),)


class Member(Base):
    __tablename__ = "members"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    upstream_id: Mapped[str] = mapped_column(String(120))
    display_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(30), default="member")  # member|moderator|admin|bot
    tier: Mapped[str | None] = mapped_column(String(40))  # synthetic access tier (general|annual|...)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime)
    left_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|left|removed
    rejoin_count: Mapped[int] = mapped_column(Integer, default=0)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False)
    dataset: Mapped[str] = mapped_column(String(60), default="synthetic")
    source_ts: Mapped[datetime | None] = mapped_column(DateTime)
    first_observed_at: Mapped[datetime | None] = mapped_column(DateTime)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    onboarding_status: Mapped[str] = mapped_column(String(20), default="unknown")  # pending|done|unknown
    tags: Mapped[list[MemberTag]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    __table_args__ = (
        UniqueConstraint("group_id", "upstream_id", name="uq_member_group_upstream"),
        Index("ix_member_name", "display_name"),
    )


class MemberTag(Base):
    __tablename__ = "member_tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    tag: Mapped[str] = mapped_column(String(60))
    __table_args__ = (UniqueConstraint("member_id", "tag"),)


class MemberNote(Base):
    __tablename__ = "member_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Post(Base):
    """Posts, comments and replies. Comments have parent_id; root_id points to the thread's post."""

    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    upstream_id: Mapped[str] = mapped_column(String(120))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    root_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # post|comment|reply
    title: Mapped[str | None] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_automated: Mapped[bool] = mapped_column(Boolean, default=False)
    client_ref: Mapped[str | None] = mapped_column(String(200), index=True)  # idempotency key of our own writes
    dataset: Mapped[str] = mapped_column(String(60), default="synthetic")
    __table_args__ = (UniqueConstraint("group_id", "upstream_id", name="uq_post_group_upstream"),)


class Reaction(Base):
    __tablename__ = "reactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    upstream_id: Mapped[str] = mapped_column(String(120))
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="like")
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    dataset: Mapped[str] = mapped_column(String(60), default="synthetic")
    __table_args__ = (UniqueConstraint("group_id", "upstream_id", name="uq_reaction_group_upstream"),)


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    upstream_id: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    # Synthetic access rule: comma-separated tiers that may access the course.
    access_tiers: Mapped[str] = mapped_column(String(200), default="general,annual")
    policy_label: Mapped[str] = mapped_column(String(80), default="SYNTHETIC evaluation policy")
    dataset: Mapped[str] = mapped_column(String(60), default="synthetic")
    __table_args__ = (UniqueConstraint("group_id", "upstream_id", name="uq_course_group_upstream"),)

    def tiers(self) -> list[str]:
        return [t.strip() for t in self.access_tiers.split(",") if t.strip()]


class Lesson(Base):
    __tablename__ = "lessons"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    upstream_id: Mapped[str] = mapped_column(String(120), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    module: Mapped[str | None] = mapped_column(String(120))
    position: Mapped[int] = mapped_column(Integer)
    video_minutes: Mapped[float | None] = mapped_column(Float)


class LessonCompletion(Base):
    """Current marked-complete state. Marked complete != watched/understood."""

    __tablename__ = "lesson_completions"
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Source time of the event that set the current state; older (late) events never override it.
    state_at: Mapped[datetime | None] = mapped_column(DateTime)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime)
    dataset: Mapped[str] = mapped_column(String(60), default="synthetic")
    __table_args__ = (UniqueConstraint("member_id", "lesson_id"),)


class ProgressEvent(Base):
    """Append-only history of observed progress changes (idempotent by upstream_id)."""

    __tablename__ = "progress_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    upstream_id: Mapped[str] = mapped_column(String(120), unique=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # completed|uncompleted
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    dataset: Mapped[str] = mapped_column(String(60), default="synthetic")


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    upstream_id: Mapped[str] = mapped_column(String(120), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("lessons.id", ondelete="SET NULL"))


class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    upstream_id: Mapped[str] = mapped_column(String(120), unique=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20))  # submitted|reviewed|needs_revision
    submitted_at: Mapped[datetime] = mapped_column(DateTime)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewer: Mapped[str | None] = mapped_column(String(120))
    feedback: Mapped[str | None] = mapped_column(Text)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    upstream_id: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    dataset: Mapped[str] = mapped_column(String(60), default="synthetic")
    __table_args__ = (UniqueConstraint("group_id", "upstream_id", name="uq_event_group_upstream"),)


class EventRegistration(Base):
    __tablename__ = "event_registrations"
    id: Mapped[int] = mapped_column(primary_key=True)
    upstream_id: Mapped[str] = mapped_column(String(120), unique=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("event_id", "member_id"),)


class EventAttendance(Base):
    __tablename__ = "event_attendance"
    id: Mapped[int] = mapped_column(primary_key=True)
    upstream_id: Mapped[str] = mapped_column(String(120), unique=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime)
    left_at: Mapped[datetime | None] = mapped_column(DateTime)
    # None means duration is unknown (source did not report leave time) — never zero-filled.
    duration_minutes: Mapped[float | None] = mapped_column(Float)
    __table_args__ = (UniqueConstraint("event_id", "member_id"),)


class LeaderboardSnapshot(Base):
    __tablename__ = "leaderboard_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    upstream_id: Mapped[str] = mapped_column(String(120), unique=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    points: Mapped[int] = mapped_column(Integer)
    level: Mapped[int] = mapped_column(Integer)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    dataset: Mapped[str] = mapped_column(String(60), default="synthetic")


class SessionEvent(Base):
    """Explicitly SYNTHETIC start/stop events used only to validate time-spent calculations."""

    __tablename__ = "session_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    upstream_id: Mapped[str] = mapped_column(String(120), unique=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # start|stop|ping
    at: Mapped[datetime] = mapped_column(DateTime, index=True)
    dataset: Mapped[str] = mapped_column(String(60), default="synthetic")


class SupportItem(Base):
    __tablename__ = "support_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), unique=True)
    # open|assigned|drafted|answered|resolved|dismissed
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    # Classification and its origin: "rule:v1", "ai:<model>", or "manual".
    label: Mapped[str] = mapped_column(String(30), default="question")
    label_source: Mapped[str] = mapped_column(String(80), default="rule:v1")
    human_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    assignee: Mapped[str | None] = mapped_column(String(80))
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    topic: Mapped[str | None] = mapped_column(String(120))
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime)
    first_response_by: Mapped[str | None] = mapped_column(String(20))  # member|staff|bot
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class KnowledgeDoc(Base):
    __tablename__ = "knowledge_docs"
    id: Mapped[int] = mapped_column(primary_key=True)
    doc_key: Mapped[str] = mapped_column(String(200), index=True)  # stable identity across versions
    title: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20))  # markdown|text|pdf|transcript|faq
    source_path: Mapped[str] = mapped_column(String(500))
    course_upstream_id: Mapped[str | None] = mapped_column(String(120))
    lesson_upstream_id: Mapped[str | None] = mapped_column(String(120))
    # Comma-separated tiers allowed; "*" means public to all members.
    access_tiers: Mapped[str] = mapped_column(String(200), default="*")
    version: Mapped[int] = mapped_column(Integer, default=1)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="approved")  # approved|pending|needs_ocr|superseded|rejected
    status_detail: Mapped[str | None] = mapped_column(Text)
    updated_label: Mapped[str | None] = mapped_column(String(60))  # e.g. "2026-05 revision"
    dataset: Mapped[str] = mapped_column(String(60), default="synthetic")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("doc_key", "version"),)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("knowledge_docs.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text)


class AIRun(Base):
    __tablename__ = "ai_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    task: Mapped[str] = mapped_column(String(40), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    model_digest: Mapped[str | None] = mapped_column(String(120))
    policy_version: Mapped[str] = mapped_column(String(40))
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    refs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # inputs by reference, not content
    retrieved: Mapped[list[Any]] = mapped_column(JSON, default=list)  # chunk ids + doc versions
    output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20))  # ok|abstain|clarify|blocked|error|timeout|invalid|unavailable
    detail: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # queued|leased|succeeded|failed|held|cancelled|expired
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4)
    run_after: Mapped[datetime] = mapped_column(DateTime, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    lease_owner: Mapped[str | None] = mapped_column(String(120))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class Action(Base):
    """An outward action. In evaluation mode delivery_target is always 'local-simulator'."""

    __tablename__ = "actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))  # reply|reminder|onboarding|moderation_flag|ban|delete|...
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    target_type: Mapped[str] = mapped_column(String(30))  # post|member|event
    target_upstream_id: Mapped[str] = mapped_column(String(120))
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"))
    support_item_id: Mapped[int | None] = mapped_column(ForeignKey("support_items.id", ondelete="SET NULL"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payload_version: Mapped[int] = mapped_column(Integer, default=1)
    # drafted|approved|queued|sending|sent|verified|failed|unknown_outcome|rejected|cancelled|held
    state: Mapped[str] = mapped_column(String(20), index=True)
    origin: Mapped[str] = mapped_column(String(60))  # manual|ai_draft|rule:<id>
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("automation_rules.id", ondelete="SET NULL"))
    ai_run_id: Mapped[int | None] = mapped_column(ForeignKey("ai_runs.id", ondelete="SET NULL"))
    consequential: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(80))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    delivery_target: Mapped[str] = mapped_column(String(40), default="local-simulator")
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    remote_id: Mapped[str | None] = mapped_column(String(120))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ActionAttempt(Base):
    __tablename__ = "action_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    action_id: Mapped[int] = mapped_column(ForeignKey("actions.id", ondelete="CASCADE"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    outcome: Mapped[str] = mapped_column(String(30))  # sent|verified|timeout_unknown|error|reconciled_found|reconciled_absent|blocked
    detail: Mapped[str | None] = mapped_column(Text)


class AutomationRule(Base):
    __tablename__ = "automation_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    trigger: Mapped[str] = mapped_column(String(40))  # new_question|stalled_progress|event_upcoming|new_member
    conditions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    action_kind: Mapped[str] = mapped_column(String(40))
    mode: Mapped[str] = mapped_column(String(10), default="draft")  # draft|auto
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    quiet_start: Mapped[str | None] = mapped_column(String(5))  # "22:00" Asia/Kolkata
    quiet_end: Mapped[str | None] = mapped_column(String(5))
    max_per_hour: Mapped[int] = mapped_column(Integer, default=5)
    max_per_day: Mapped[int] = mapped_column(Integer, default=30)
    expire_after_minutes: Mapped[int] = mapped_column(Integer, default=240)
    evaluation_only: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class Segment(Base):
    __tablename__ = "segments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    rule: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    description: Mapped[str | None] = mapped_column(Text)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    worker_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    pid: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    beat_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20))
    current_job: Mapped[str | None] = mapped_column(String(120))
    wall_beat_at: Mapped[datetime | None] = mapped_column(DateTime)


class SyncState(Base):
    __tablename__ = "sync_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40))
    resource: Mapped[str] = mapped_column(String(40))
    cursor: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="never")  # never|ok|partial|error|auth_expired
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    items_last_run: Mapped[int] = mapped_column(Integer, default=0)
    items_total: Mapped[int] = mapped_column(Integer, default=0)
    coverage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("source", "resource"),)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(300))
    entity: Mapped[str] = mapped_column(String(40))  # members|posts|completions
    fmt: Mapped[str] = mapped_column(String(10))
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))  # previewed|committed|rejected|deleted
    mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_ok: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[Any]] = mapped_column(JSON, default=list)
    provenance_note: Mapped[str | None] = mapped_column(Text)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, index=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(80))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, index=True)
    level: Mapped[str] = mapped_column(String(10))  # info|warn|error
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(40), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user|assistant
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ai_run_id: Mapped[int | None] = mapped_column(ForeignKey("ai_runs.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class SyncDeferred(Base):
    """Changes whose dependencies (e.g. a parent post) have not arrived yet. Retried on later syncs."""

    __tablename__ = "sync_deferred"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40))
    seq: Mapped[int] = mapped_column(Integer)
    entity: Mapped[str] = mapped_column(String(30))
    upstream_id: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(200))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("source", "entity", "upstream_id", "seq"),)


class KnowledgeEmbedding(Base):
    """Embedding vector (float32 bytes) for a knowledge chunk, per embedding model."""

    __tablename__ = "knowledge_embeddings"
    chunk_id: Mapped[int] = mapped_column(ForeignKey("knowledge_chunks.id", ondelete="CASCADE"), primary_key=True)
    model: Mapped[str] = mapped_column(String(120), primary_key=True)
    dim: Mapped[int] = mapped_column(Integer)
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime)
