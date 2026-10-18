"""The single background worker.

- Single instance per data directory (OS file lock) — a second launch exits immediately.
- Durable jobs with leases; scheduling uses dedupe keys bucketed by time, so restarts never duplicate work.
- Heartbeat row for the UI (worker liveness, current job).
- Sleep/wake detection: if the wall clock jumps, outdated jobs past `expires_at` are expired, not burst-sent.
- Graceful shutdown on SIGTERM/SIGINT: finish the current job, then exit.
"""
from __future__ import annotations

import fcntl
import logging
import os
import signal
import socket
import sys
import time
import traceback
from datetime import UTC, datetime, timedelta
from logging.handlers import RotatingFileHandler
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from . import clock, db
from .config import get_settings
from .models import Job, WorkerHeartbeat
from .services import jobs, notify
from .services.handlers import HANDLERS, Retry
from .timeutil import IST

log = logging.getLogger("worker")
_stop = False


def _on_signal(signum: int, _frame: Any) -> None:
    global _stop
    _stop = True
    log.info("signal %s received: finishing current job then exiting", signum)


def acquire_lock(path: str) -> Any:
    fh = open(path, "a+")  # noqa: SIM115 (held for process lifetime)
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def schedule(session: Any, now: datetime, sync_interval_s: int) -> None:
    """Idempotent periodic enqueues (bucketed dedupe keys)."""
    bucket = int(now.timestamp() // sync_interval_s)
    jobs.enqueue(session, "sync", f"sync:{bucket}", {}, priority=4, max_attempts=3,
                 expires_at=now + timedelta(seconds=sync_interval_s * 3))
    jobs.enqueue(session, "scan_rules", f"scan_rules:{int(now.timestamp() // 300)}", {}, priority=6, max_attempts=2,
                 expires_at=now + timedelta(minutes=15))
    jobs.enqueue(session, "embed_chunks", f"embed_chunks:{int(now.timestamp() // 600)}", {}, priority=7, max_attempts=1,
                 expires_at=now + timedelta(minutes=30))
    local = now.replace(tzinfo=UTC).astimezone(IST)
    day = local.date().isoformat()
    if local.hour >= 8:
        jobs.enqueue(session, "daily_summary", f"daily_summary:{day}", {}, priority=7, max_attempts=2)
    if local.hour >= 2:
        jobs.enqueue(session, "backup", f"backup:{day}", {}, priority=8, max_attempts=2)
        jobs.enqueue(session, "retention", f"retention:{day}", {}, priority=9, max_attempts=2)
    session.commit()


def expire_outdated(session: Any) -> int:
    now = clock.now()
    rows = session.execute(select(Job).where(Job.status == "queued", Job.expires_at.is_not(None), Job.expires_at < now)).scalars().all()
    for j in rows:
        jobs.expire(session, j, "expired: outdated after downtime or delay")
        if j.kind == "publish_action":
            from .models import Action

            a = session.get(Action, j.payload.get("action_id"))
            if a and a.state in ("approved", "queued"):
                a.state, a.error = "cancelled", "Expired before sending (outdated after downtime)"
    if rows:
        notify.info(session, "Outdated jobs expired", f"{len(rows)} queued job(s) passed their expiry and were not run "
                    "(catch-up rule: no burst of stale reminders or replies).")
    session.commit()
    return len(rows)


def heartbeat(session: Any, worker_id: str, started: datetime, status: str, current: str | None) -> None:
    hb = session.get(WorkerHeartbeat, worker_id)
    if hb is None:
        hb = WorkerHeartbeat(worker_id=worker_id, pid=os.getpid(), started_at=started, beat_at=clock.now(), status=status)
        session.add(hb)
    hb.beat_at, hb.wall_beat_at, hb.status, hb.current_job = clock.now(), clock.wall_now(), status, current
    session.commit()


def run_job(session: Any, job: Job) -> None:
    handler = HANDLERS.get(job.kind)
    if handler is None:
        jobs.fail(session, job, f"no handler for {job.kind}")
        return
    if job.expires_at and clock.now() > job.expires_at and job.kind not in ("publish_action", "reconcile_action"):
        jobs.expire(session, job, "expired before execution")
        return
    try:
        result = handler(session, job)
        session.refresh(job)
        jobs.complete(session, job, result)
    except Retry as e:
        session.rollback()
        session.refresh(job)
        jobs.retry_later(session, job, str(e), e.delay_s)
    except Exception as e:  # unexpected: record and back off, never swallow silently
        session.rollback()
        session.refresh(job)
        log.error("job %s failed: %s", job.id, traceback.format_exc())
        jobs.retry_later(session, job, f"{e.__class__.__name__}: {e}")


def main(max_iterations: int | None = None) -> int:
    s = get_settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    (s.data_dir / "logs").mkdir(exist_ok=True)
    handler = RotatingFileHandler(s.data_dir / "logs" / "worker.log", maxBytes=s.log_max_bytes, backupCount=3)
    logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler(sys.stdout)],
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    lock = acquire_lock(str(s.data_dir / "worker.lock"))
    if lock is None:
        log.warning("another worker already holds the lock for %s — exiting", s.data_dir)
        return 3
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    started = clock.now()
    log.info("worker %s started (run_mode=%s, data=%s)", worker_id, s.run_mode, s.data_dir)
    last_wall = time.time()
    last_sched = 0.0
    it = 0
    with db.session_scope() as session:
        heartbeat(session, worker_id, started, "starting", None)
        expire_outdated(session)
    while not _stop:
        it += 1
        gap = time.time() - last_wall
        last_wall = time.time()
        ran_job = False
        try:
            ran_job, scheduled = _iteration(gap, worker_id, started, s, last_sched)
            if scheduled:
                last_sched = time.time()
        except OperationalError as e:  # e.g. database locked by a long writer: transient, retry next loop
            log.warning("database busy (%s); retrying", getattr(e, "orig", e))
        if max_iterations and it >= max_iterations:
            break
        if not ran_job:
            time.sleep(s.worker_poll_s)
    with db.session_scope() as session:
        heartbeat(session, worker_id, started, "stopped", None)
    log.info("worker %s stopped", worker_id)
    return 0


def _iteration(gap: float, worker_id: str, started: datetime, s: Any, last_sched: float) -> tuple[bool, bool]:
    """One loop iteration. Returns (ran_a_job, enqueued_periodic_jobs)."""
    scheduled = False
    with db.session_scope() as session:
        if gap > 120:
            log.warning("wall-clock gap of %.0fs detected (sleep/suspend?) — applying catch-up rules", gap)
            notify.info(session, "Worker resumed after a pause", f"No processing for ~{gap / 60:.0f} min (sleep, "
                        "shutdown or suspension). Outdated jobs are expired instead of sent in a burst.")
            session.commit()
            expire_outdated(session)
        if time.time() - last_sched >= 15:
            schedule(session, clock.now(), s.sync_interval_s)
            scheduled = True
        job = jobs.lease(session, worker_id, s.worker_lease_s)
        heartbeat(session, worker_id, started, "running" if job else "idle", f"{job.kind}#{job.id}" if job else None)
        if job is None:
            return False, scheduled
        log.info("running job %s %s", job.id, job.dedupe_key)
        run_job(session, job)
        heartbeat(session, worker_id, started, "idle", None)
        return True, scheduled


if __name__ == "__main__":
    raise SystemExit(main())
