"""Provider-neutral community adapter contract.

Every adapter declares its source, mode, supported operations and coverage notes. Unsupported
operations raise `UnsupportedOperation` explicitly — they never return empty results that could be
mistaken for an empty community.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# Entity kinds carried by the change feed, in dependency order (parents before children).
ENTITY_ORDER = [
    "group",
    "member",
    "course",
    "lesson",
    "assignment",
    "event",
    "post",
    "reaction",
    "progress",
    "submission",
    "registration",
    "attendance",
    "leaderboard",
    "session",
]

OPERATIONS = [
    "read.members",
    "read.posts",
    "read.reactions",
    "read.courses",
    "read.progress",
    "read.assignments",
    "read.events",
    "read.attendance",
    "read.leaderboard",
    "read.sessions",
    "write.comment",
    "write.member_message",
    "write.member_action",
    "reconcile.thread_lookup",
]


class ConnectorError(Exception):
    """Base class. `kind` is shown to operators; never treat it as an empty result."""

    kind = "connector_error"


class AuthExpired(ConnectorError):
    kind = "auth_expired"


class ConnectorUnavailable(ConnectorError):
    kind = "unavailable"


class RateLimited(ConnectorError):
    kind = "rate_limited"

    def __init__(self, msg: str, retry_after_s: float = 30.0) -> None:
        super().__init__(msg)
        self.retry_after_s = retry_after_s


class TimeoutUnknownOutcome(ConnectorError):
    """A write timed out after it may have been sent. The outcome must be reconciled before retry."""

    kind = "timeout_unknown_outcome"


class UnsupportedOperation(ConnectorError):
    kind = "unsupported"


class ModeViolation(ConnectorError):
    """Raised when evaluation mode would be bypassed (e.g. constructing a live connector)."""

    kind = "mode_violation"


@dataclass
class AdapterInfo:
    source: str
    mode: str  # evaluation | import | live
    display_name: str
    simulated: bool
    operations: dict[str, bool]
    coverage_notes: list[str] = field(default_factory=list)


@dataclass
class Change:
    seq: int
    entity: str
    upstream_id: str
    op: str  # upsert | delete
    payload: dict[str, Any]


@dataclass
class ChangePage:
    changes: list[Change]
    next_cursor: str | None
    has_more: bool


@dataclass
class WriteResult:
    remote_id: str
    status: str  # sent
    detail: dict[str, Any] = field(default_factory=dict)


class CommunityAdapter(ABC):
    info: AdapterInfo

    def supports(self, op: str) -> bool:
        return self.info.operations.get(op, False)

    def require(self, op: str) -> None:
        if not self.supports(op):
            raise UnsupportedOperation(f"{self.info.source} does not support {op}")

    @abstractmethod
    def health(self) -> dict[str, Any]: ...

    @abstractmethod
    def fetch_changes(self, cursor: str | None, limit: int = 500) -> ChangePage: ...

    @abstractmethod
    def list_thread(self, post_upstream_id: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def publish_comment(
        self, *, group_upstream_id: str, parent_upstream_id: str, body: str, idempotency_key: str
    ) -> WriteResult: ...

    @abstractmethod
    def send_member_message(
        self, *, group_upstream_id: str, member_upstream_id: str, body: str, idempotency_key: str
    ) -> WriteResult: ...

    @abstractmethod
    def apply_member_action(
        self,
        *,
        group_upstream_id: str,
        member_upstream_id: str,
        action: str,
        params: dict[str, Any],
        idempotency_key: str,
    ) -> WriteResult: ...

    @abstractmethod
    def find_by_idempotency_key(self, kind: str, idempotency_key: str) -> dict[str, Any] | None: ...
