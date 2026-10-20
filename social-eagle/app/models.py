"""Normalized data model.

Every observation table carries provenance (``ProvenanceMixin``): where it came
from, how, when it happened vs. when we saw it, timestamp precision, the
original displayed value, a record hash, the parser version and the sync run.

All timestamps are stored as naive UTC datetimes.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# Field origins
OBSERVED = "observed"
IMPORTED = "imported"
CALCULATED = "calculated"
HUMAN = "human_labelled"
AI_SUGGESTED = "ai_suggested"


class ProvenanceMixin:
    source_ref: Mapped[str | None] = mapped_column(String(500))  # URL or import reference
    source_mode: Mapped[str] = mapped_column(String(16), default="test")
    source_method: Mapped[str] = mapped_column(String(32), default="import")  # public_read|import|fixture|manual
    field_origin: Mapped[str] = mapped_column(String(20), default=IMPORTED)
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    source_tz: Mapped[str | None] = mapped_column(String(40))
    timestamp_precision: Mapped[str | None] = mapped_column(String(16))  # second|minute|day|relative|unknown
    displayed_value: Mapped[str | None] = mapped_column(String(120))
    record_hash: Mapped[str | None] = mapped_column(String(64))
    parser_version: Mapped[str | None] = mapped_column(String(40))
    sync_run_id: Mapped[int | None] = mapped_column(ForeignKey("sync_runs.id"))


class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id"), index=True)
    source_name: Mapped[str] = mapped_column(String(80))  # e.g. "feed", "progress_import", "support_import"
    mode: Mapped[str] = mapped_column(String(16))
    method: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|success|partial|failed
    coverage_start: Mapped[datetime | None] = mapped_column(DateTime)
    coverage_end: Mapped[datetime | None] = mapped_column(DateTime)
    coverage_status: Mapped[str] = mapped_column(String(16), default="unknown")  # complete|partial|unknown
    pages_captured: Mapped[list | None] = mapped_column(JSON)
    known_gaps: Mapped[list | None] = mapped_column(JSON)
    failed_sources: Mapped[list | None] = mapped_column(JSON)
    parser_version: Mapped[str | None] = mapped_column(String(40))
    records_seen: Mapped[int] = mapped_column(Integer, default=0)
    records_new: Mapped[int] = mapped_column(Integer, default=0)
    records_changed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("ix_sync_source_time", "community_id", "source_name", "started_at"),)


class Community(Base):
    __tablename__ = "communities"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(String(500))
    is_company_community: Mapped[bool] = mapped_column(Boolean, default=False)  # Social Eagle vs external reference
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    displayed_member_total: Mapped[str | None] = mapped_column(String(40))  # as displayed, e.g. "12.3k"
    displayed_online: Mapped[str | None] = mapped_column(String(40))
    totals_observed_at: Mapped[datetime | None] = mapped_column(DateTime)
    expected_sources: Mapped[list | None] = mapped_column(JSON)  # source names a daily report depends on


class Member(Base):
    __tablename__ = "members"
    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id"))
    source_member_id: Mapped[str] = mapped_column(String(120))
    display_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16), default="member")  # member|staff|bot|admin
    joined_at: Mapped[datetime | None] = mapped_column(DateTime)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime)
    source_ref: Mapped[str | None] = mapped_column(String(500))
    tags: Mapped[list | None] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("community_id", "source_member_id"), Index("ix_member_name", "community_id", "display_name"))


class MemberAlias(Base):
    """Display-name history so renames don't break identity."""
    __tablename__ = "member_aliases"
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("member_id", "display_name"),)


class MemberNote(Base):
    __tablename__ = "member_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Cohort(Base):
    __tablename__ = "cohorts"
    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id"))
    key: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"))
    starts_on: Mapped[datetime | None] = mapped_column(DateTime)
    ends_on: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("community_id", "key"),)


class CohortMembership(ProvenanceMixin, Base):
    __tablename__ = "cohort_memberships"
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    cohort_id: Mapped[int] = mapped_column(ForeignKey("cohorts.id"), index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("member_id", "cohort_id", "valid_from"),)


class AccessPeriod(ProvenanceMixin, Base):
    """Business subscription/access label history (General / Annual / VIP).
    Deliberately NOT assumed to map to a Skool billing product or course access."""
    __tablename__ = "access_periods"
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    label: Mapped[str] = mapped_column(String(40))  # general|annual|vip
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|cancelled|expired|unknown
    valid_from: Mapped[datetime] = mapped_column(DateTime)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("member_id", "label", "valid_from"),)


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id"))
    source_course_id: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    access_note: Mapped[str | None] = mapped_column(String(200))  # e.g. "VIP only (synthetic rule)"
    __table_args__ = (UniqueConstraint("community_id", "source_course_id"),)


class Lesson(Base):
    __tablename__ = "lessons"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    source_lesson_id: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    position: Mapped[int] = mapped_column(Integer, default=0)
    released_at: Mapped[datetime | None] = mapped_column(DateTime)
    optional: Mapped[bool] = mapped_column(Boolean, default=False)
    body: Mapped[str | None] = mapped_column(Text)  # transcript/notes excerpt for permission-scoped search
    __table_args__ = (UniqueConstraint("course_id", "source_lesson_id"),)


class Entitlement(ProvenanceMixin, Base):
    """Course access (unlocked / granted) — separate from subscription label."""
    __tablename__ = "entitlements"
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("member_id", "course_id", "valid_from"),)


class CourseEnrolment(ProvenanceMixin, Base):
    """Expected participation in a course, optionally through a cohort/batch."""
    __tablename__ = "course_enrolments"
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    cohort_id: Mapped[int | None] = mapped_column(ForeignKey("cohorts.id"))
    enrolled_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("member_id", "course_id", "enrolled_at"),)


class LessonDeadline(Base):
    """A lesson assigned to a cohort with a due date (configured, never guessed)."""
    __tablename__ = "lesson_deadlines"
    id: Mapped[int] = mapped_column(primary_key=True)
    cohort_id: Mapped[int] = mapped_column(ForeignKey("cohorts.id"), index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"))
    due_at: Mapped[datetime] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("cohort_id", "lesson_id"),)


class ProgressSnapshot(ProvenanceMixin, Base):
    """Course-level recorded completion as observed at a point in time."""
    __tablename__ = "progress_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    completed_lessons: Mapped[int | None] = mapped_column(Integer)
    total_lessons: Mapped[int | None] = mapped_column(Integer)  # the denominator as known at observation
    lesson_set_hash: Mapped[str | None] = mapped_column(String(64))  # comparability key
    completed_lesson_ids: Mapped[list | None] = mapped_column(JSON)  # source lesson ids marked complete
    __table_args__ = (
        Index("ix_progress_member_course_time", "member_id", "course_id", "observed_at"),
        UniqueConstraint("member_id", "course_id", "observed_at"),
    )


class Post(ProvenanceMixin, Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id"))
    source_post_id: Mapped[str] = mapped_column(String(120))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), index=True)
    category: Mapped[str | None] = mapped_column(String(120))
    title: Mapped[str | None] = mapped_column(String(500))
    excerpt: Mapped[str | None] = mapped_column(Text)
    is_excerpt: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    displayed_like_count: Mapped[int | None] = mapped_column(Integer)
    displayed_comment_count: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (
        UniqueConstraint("community_id", "source_post_id"),
        Index("ix_post_comm_created", "community_id", "created_at"),
    )


class Comment(ProvenanceMixin, Base):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id"))
    source_comment_id: Mapped[str] = mapped_column(String(120))
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    parent_comment_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id"))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), index=True)
    excerpt: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (
        UniqueConstraint("community_id", "source_comment_id"),
        Index("ix_comment_comm_created", "community_id", "created_at"),
    )


class ContentVersion(Base):
    """Prior versions of edited posts/comments (never silently overwritten)."""
    __tablename__ = "content_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(500))
    excerpt: Mapped[str | None] = mapped_column(Text)
    record_hash: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    sync_run_id: Mapped[int | None] = mapped_column(ForeignKey("sync_runs.id"))
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", "version"),)


class Reaction(ProvenanceMixin, Base):
    """A like. Given by ``actor_id``; received by ``target_author_id``."""
    __tablename__ = "reactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id"))
    source_reaction_id: Mapped[str] = mapped_column(String(160))
    actor_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(16))  # post|comment
    target_source_id: Mapped[str] = mapped_column(String(120))
    target_author_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    removed_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (
        UniqueConstraint("community_id", "source_reaction_id"),
        Index("ix_reaction_comm_created", "community_id", "created_at"),
    )


class AssignmentDef(Base):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id"))
    key: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(300))
    cohort_id: Mapped[int | None] = mapped_column(ForeignKey("cohorts.id"))
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime)  # only if supplied
    category_mapping: Mapped[str | None] = mapped_column(String(120))  # configured post category
    __table_args__ = (UniqueConstraint("community_id", "key"),)


class Submission(ProvenanceMixin, Base):
    __tablename__ = "submissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int | None] = mapped_column(ForeignKey("assignments.id"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    source_submission_id: Mapped[str] = mapped_column(String(160), unique=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"))
    submitted_at: Mapped[datetime] = mapped_column(DateTime)
    classification: Mapped[str] = mapped_column(String(20), default="configured")  # configured|manual|ambiguous


class Feedback(ProvenanceMixin, Base):
    """Review status, feedback delivery and assessment result are separate facts."""
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    source_feedback_id: Mapped[str] = mapped_column(String(160), unique=True)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    feedback_delivered_at: Mapped[datetime | None] = mapped_column(DateTime)
    feedback_channel: Mapped[str | None] = mapped_column(String(40))  # comment|dm|call|import
    assessment_result: Mapped[str | None] = mapped_column(String(40))  # pass|resubmit|null
    follow_up: Mapped[str | None] = mapped_column(String(300))


class Win(ProvenanceMixin, Base):
    __tablename__ = "wins"
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"), unique=True)
    category: Mapped[str | None] = mapped_column(String(80))
    recorded_at: Mapped[datetime] = mapped_column(DateTime)
    verification: Mapped[str] = mapped_column(String(20), default="self_reported")  # self_reported|verified


QUESTION_STATES = (
    "new", "researching", "awaiting_member", "ready_to_answer", "answering",
    "answered", "awaiting_owner", "blocked", "closed",
)


class SupportQuestion(ProvenanceMixin, Base):
    __tablename__ = "support_questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id"))
    source_question_id: Mapped[str] = mapped_column(String(160))
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"))
    comment_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id"))
    asked_at: Mapped[datetime] = mapped_column(DateTime)
    text: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="new")
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"))
    classification_origin: Mapped[str] = mapped_column(String(20), default=IMPORTED)
    __table_args__ = (UniqueConstraint("community_id", "source_question_id"), Index("ix_q_comm_asked", "community_id", "asked_at"))


SUPPORT_EVENT_KINDS = (
    "staff_response", "peer_response", "bot_response", "clarification_request", "member_reply",
    "assigned", "resolution_confirmed", "reopened", "closed",
)


class SupportEvent(ProvenanceMixin, Base):
    __tablename__ = "support_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("support_questions.id"), index=True)
    source_event_id: Mapped[str] = mapped_column(String(160), unique=True)
    kind: Mapped[str] = mapped_column(String(30))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"))
    at: Mapped[datetime] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(Text)


class LeaderboardSnapshot(ProvenanceMixin, Base):
    __tablename__ = "leaderboard_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id"), index=True)
    period: Mapped[str] = mapped_column(String(16))  # 7d|30d|all
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False)  # False = visible snippet only
    entries: Mapped[list[LeaderboardEntry]] = relationship(back_populates="snapshot", cascade="all, delete-orphan")


class LeaderboardEntry(Base):
    __tablename__ = "leaderboard_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("leaderboard_snapshots.id"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    rank: Mapped[int | None] = mapped_column(Integer)
    points: Mapped[int | None] = mapped_column(Integer)
    snapshot: Mapped[LeaderboardSnapshot] = relationship(back_populates="entries")


class ReportRun(Base):
    __tablename__ = "report_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id"))
    report_date: Mapped[str] = mapped_column(String(10))  # local Asia/Kolkata date YYYY-MM-DD
    range_end_date: Mapped[str] = mapped_column(String(10))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("report_runs.id"))
    trigger: Mapped[str] = mapped_column(String(16))  # scheduled|catchup|manual
    status: Mapped[str] = mapped_column(String(16))  # complete|degraded|unavailable
    generated_at: Mapped[datetime] = mapped_column(DateTime)
    data_cutoff: Mapped[datetime] = mapped_column(DateTime)
    interval_start_utc: Mapped[datetime] = mapped_column(DateTime)
    interval_end_utc: Mapped[datetime] = mapped_column(DateTime)
    calc_version: Mapped[str] = mapped_column(String(40))
    content_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    revision_reason: Mapped[str | None] = mapped_column(String(300))
    output_dir: Mapped[str | None] = mapped_column(String(500))
    __table_args__ = (UniqueConstraint("community_id", "report_date", "range_end_date", "revision"),)


class Job(Base):
    """Durable job queue. ``dedupe_key`` is unique so the same job can't be enqueued twice."""
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    priority: Mapped[int] = mapped_column(Integer, default=5)  # lower runs first
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|done|failed|expired
    run_after: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    lease_owner: Mapped[str | None] = mapped_column(String(80))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    __table_args__ = (Index("ix_jobs_pick", "status", "priority", "run_after"),)


class SchedulerEvent(Base):
    """Missed runs, catch-ups and worker heartbeats."""
    __tablename__ = "scheduler_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))  # heartbeat|missed_run|catchup|expired_run
    at: Mapped[datetime] = mapped_column(DateTime)
    detail: Mapped[dict | None] = mapped_column(JSON)


class OutboxMessage(Base):
    """A generated report is not a delivered notification; delivery state lives here."""
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    channel: Mapped[str] = mapped_column(String(20))  # in_app|email (disabled)|sheets (disabled)
    recipient: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(300))
    report_run_id: Mapped[int | None] = mapped_column(ForeignKey("report_runs.id"))
    state: Mapped[str] = mapped_column(String(20), default="pending")  # pending|sent|failed|unknown|blocked
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base):
    """Human corrections with an audit trail."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String(60))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(500))
    actor: Mapped[str] = mapped_column(String(120))
    at: Mapped[datetime] = mapped_column(DateTime)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class AppState(Base):
    __tablename__ = "app_state"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
