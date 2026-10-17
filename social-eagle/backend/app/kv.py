"""Small typed key/value settings store backed by the `settings` table."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from .models import Setting

DEFAULTS: dict[str, Any] = {
    "paused": False,
    "paused_reason": None,
    "thresholds": {
        "new_member_days": 14,
        "quiet_days": 21,
        "stalled_progress_days": 14,
        "unanswered_hours": 24,
        # Phrases (not single common words) to avoid flagging ordinary questions as support needs.
        "support_keywords": ["please help", "need help", "help!", "stuck", "refund", "cancel my", "can't access",
                             "cannot access", "error", "not working", "locked out"],
    },
    "ai_task_modes": {"faq_reply": "draft", "owner_chat": "enabled", "classify": "enabled"},
    "dataset_selection": ["synthetic"],
    "retention_days": {"ai_runs": 90, "audit_log": 365, "chat_messages": 90},
}


def get(session: Session, key: str) -> Any:
    row = session.get(Setting, key)
    if row is None:
        return DEFAULTS.get(key)
    return row.value


def put(session: Session, key: str, value: Any) -> None:
    row = session.get(Setting, key)
    now = datetime.now(UTC).replace(tzinfo=None)
    if row is None:
        session.add(Setting(key=key, value=value, updated_at=now))
    else:
        row.value = value
        row.updated_at = now
