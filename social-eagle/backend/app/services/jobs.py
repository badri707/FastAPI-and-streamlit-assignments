"""Durable database job queue.

- `dedupe_key` is UNIQUE: enqueueing the same logical job twice (restarts, double launches) is a no-op.
- Leasing is a single atomic UPDATE ... RETURNING, so two workers can never hold the same job.
- `run_after` / `expires_at` use the controllable clock (scheduling semantics). Lease expiry uses wall time
  (process liveness), so advancing the evaluation clock never steals a lease from a live worker.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import DateTime, bindparam, select, text
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from .. import clock, kv
from ..models import Job
from . import notify

EXTERNAL_KINDS = ("publish_action", "reconcile_action")  # paused => not leased


def enqueue(
    session: Session,
    kind: str,
    dedupe_key: str,
    payload: dict[str, Any] | None = None,
    *,
    run_after: datetime | None = None,
    expires_at: datetime | None = None,
    priority: int = 5,
    max_attempts: int = 4,
) -> tuple[Job, bool]:
    """Returns (job, created)."""
    now = clock.now()
    stmt = insert(Job).values(
        kind=kind, dedupe_key=dedupe_key, payload=payload or {}, status="queued", priority=priority, attempts=0,
        max_attempts=max_attempts, run_after=run_after or now, expires_at=expires_at, created_at=now, updated_at=now,
    ).on_conflict_do_nothing(index_elements=["dedupe_key"])
    res = session.execute(stmt)
    session.flush()
    job = session.execute(select(Job).filter_by(dedupe_key=dedupe_key)).scalar_one()
    return job, bool(res.rowcount)


def lease(session: Session, worker_id: str, lease_s: int) -> Job | None:
    now = clock.now()
    wall = clock.wall_now()
    paused = bool(kv.get(session, "paused"))
    excluded = "AND kind NOT IN ('publish_action','reconcile_action')" if paused else ""
    row = session.execute(text(f"""
        UPDATE jobs SET status='leased', lease_owner=:w, lease_expires_at=:exp, attempts=attempts+1, updated_at=:now
        WHERE id = (
            SELECT id FROM jobs
            WHERE ((status='queued' AND run_after <= :now) OR (status='leased' AND lease_expires_at < :wall)) {excluded}
            ORDER BY priority, run_after, id LIMIT 1
        ) RETURNING id
    """).bindparams(bindparam("exp", type_=DateTime), bindparam("now", type_=DateTime), bindparam("wall", type_=DateTime)),
        {"w": worker_id, "exp": wall + timedelta(seconds=lease_s), "now": now, "wall": wall}).fetchone()  # noqa: S608
    session.commit()
    if row is None:
        return None
    job = session.get(Job, row[0])
    session.refresh(job)
    return job


def complete(session: Session, job: Job, result: dict[str, Any] | None = None) -> None:
    job.status, job.result, job.lease_owner, job.lease_expires_at = "succeeded", result or {}, None, None
    job.updated_at = clock.now()
    session.commit()


def retry_later(session: Session, job: Job, error: str, delay_s: float | None = None) -> None:
    if job.attempts >= job.max_attempts:
        fail(session, job, f"max attempts reached: {error}")
        return
    backoff = delay_s if delay_s is not None else min(15 * 60, 10 * (2 ** max(job.attempts - 1, 0)))
    job.status, job.last_error = "queued", error[:2000]
    job.run_after = clock.now() + timedelta(seconds=backoff)
    job.lease_owner = job.lease_expires_at = None
    job.updated_at = clock.now()
    session.commit()


def fail(session: Session, job: Job, error: str) -> None:
    job.status, job.last_error, job.lease_owner, job.lease_expires_at = "failed", error[:2000], None, None
    job.updated_at = clock.now()
    notify.raise_(session, f"job-failed:{job.id}", "error", f"Job failed: {job.kind}", f"{job.dedupe_key}: {error[:300]}")
    session.commit()


def hold(session: Session, job: Job, reason: str) -> None:
    job.status, job.last_error, job.lease_owner, job.lease_expires_at = "held", reason[:2000], None, None
    job.updated_at = clock.now()
    notify.raise_(session, f"job-held:{job.id}", "warn", f"Job held for review: {job.kind}", reason[:300])
    session.commit()


def expire(session: Session, job: Job, reason: str) -> None:
    job.status, job.last_error, job.lease_owner, job.lease_expires_at = "expired", reason, None, None
    job.updated_at = clock.now()
    session.commit()


def queue_stats(session: Session) -> dict[str, Any]:
    rows = session.execute(text("SELECT status, COUNT(*), MIN(run_after) FROM jobs GROUP BY status")).fetchall()
    out: dict[str, Any] = {r[0]: r[1] for r in rows}
    oldest = session.execute(text("SELECT MIN(created_at) FROM jobs WHERE status IN ('queued','leased')")).scalar()
    if isinstance(oldest, str):
        oldest = datetime.fromisoformat(oldest)
    out["oldest_queued_age_s"] = (clock.now() - oldest).total_seconds() if oldest else None
    return out
