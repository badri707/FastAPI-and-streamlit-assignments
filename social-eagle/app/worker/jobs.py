"""Durable database job queue with leases.

* ``dedupe_key`` is UNIQUE: enqueuing the same logical job twice is a no-op, even across
  restarts or two workers.
* Claiming is a single atomic UPDATE … RETURNING, so two workers can't run the same job.
* A crashed worker's job becomes claimable again once its lease expires.
* The queue is bounded: enqueue refuses work beyond ``MAX_QUEUED`` (backpressure).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as m
from app.timeutil import sql_ts

MAX_QUEUED = 10_000


class QueueFull(RuntimeError):
    pass


def enqueue(s: Session, kind: str, dedupe_key: str, payload: dict, now: datetime, *, priority: int = 5,
            run_after: datetime | None = None, max_attempts: int = 3) -> tuple[m.Job, bool]:
    existing = s.scalar(select(m.Job).where(m.Job.dedupe_key == dedupe_key))
    if existing:
        return existing, False
    queued = s.scalar(select(func.count()).select_from(m.Job).where(m.Job.status == "queued")) or 0
    if queued >= MAX_QUEUED:
        raise QueueFull(f"job queue holds {queued} queued jobs; retry later")
    job = m.Job(kind=kind, dedupe_key=dedupe_key, payload=payload, priority=priority, run_after=run_after or now,
                max_attempts=max_attempts, created_at=now, updated_at=now)
    try:
        with s.begin_nested():
            s.add(job)
            s.flush()
    except IntegrityError:
        raced = s.scalar(select(m.Job).where(m.Job.dedupe_key == dedupe_key))
        assert raced is not None
        return raced, False
    return job, True


def claim(s: Session, owner: str, now: datetime, lease_seconds: int = 300) -> m.Job | None:
    row = s.execute(text(
        "UPDATE jobs SET status='running', lease_owner=:owner, lease_expires_at=:exp, attempts=attempts+1, updated_at=:now "
        "WHERE id = (SELECT id FROM jobs WHERE (status='queued' AND run_after <= :now) "
        "OR (status='running' AND lease_expires_at < :now) ORDER BY priority, run_after, id LIMIT 1) "
        "RETURNING id"), {"owner": owner, "exp": sql_ts(now + timedelta(seconds=lease_seconds)), "now": sql_ts(now)}).first()
    if row is None:
        return None
    s.expire_all()
    return s.get(m.Job, row[0])


def complete(s: Session, job: m.Job, now: datetime) -> None:
    job.status, job.lease_owner, job.lease_expires_at, job.updated_at = "done", None, None, now


def fail(s: Session, job: m.Job, now: datetime, error: str) -> None:
    job.last_error = error[:2000]
    job.lease_owner = job.lease_expires_at = None
    job.updated_at = now
    if job.attempts >= job.max_attempts:
        job.status = "failed"  # visible in the failed-job review list
    else:
        job.status = "queued"
        job.run_after = now + timedelta(seconds=30 * 2 ** (job.attempts - 1))


def queue_health(s: Session, now: datetime) -> dict:
    rows = s.execute(select(m.Job.status, func.count(), func.min(m.Job.created_at)).group_by(m.Job.status)).all()
    out = {st: {"count": n, "oldest_age_s": (now - oldest).total_seconds() if oldest else None} for st, n, oldest in rows}
    return out
