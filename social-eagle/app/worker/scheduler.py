"""Daily report scheduler and the worker loop.

Policy (documented in docs/DAILY_REPORT_SPEC.md):
* The report for local date D is due at D+1 at the configured time (default 09:00 Asia/Kolkata).
* The scheduler remembers the last date it planned (``app_state``), so restarts neither skip
  nor duplicate dates; job dedupe keys make planning idempotent even with two workers.
* If the worker wakes more than 60 minutes after a due time, the run is recorded as a
  ``missed_run`` and generated as a clearly labelled ``catchup`` report.
* Dates older than ``catchup_max_days`` are recorded as ``expired_run`` and not generated
  automatically (they can still be generated with Run now).
"""
from __future__ import annotations

import logging
import os
import socket
import time as _time
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.config import REPORT_TZ, Mode, Settings, get_settings
from app.db import get_engine, session_scope
from app.reports.daily import issue_report
from app.timeutil import Clock, iso, local_date_of, to_utc_naive
from app.worker import jobs

log = logging.getLogger("social_eagle.worker")
LATE_TOLERANCE = timedelta(minutes=60)


def due_at(d: date, settings: Settings) -> datetime:
    local = datetime.combine(d + timedelta(days=1), time(settings.report_hour_local, settings.report_minute_local),
                             tzinfo=REPORT_TZ)
    return to_utc_naive(local)


def _state(s: Session, key: str) -> str | None:
    row = s.get(m.AppState, key)
    return row.value if row else None


def _set_state(s: Session, key: str, value: str) -> None:
    row = s.get(m.AppState, key)
    if row:
        row.value = value
    else:
        s.add(m.AppState(key=key, value=value))


def is_paused(s: Session) -> bool:
    return _state(s, "paused") == "1"


def set_paused(s: Session, paused: bool) -> None:
    _set_state(s, "paused", "1" if paused else "0")


def plan_daily_reports(s: Session, community: m.Community, now: datetime, settings: Settings) -> list[m.Job]:
    key = f"daily:last_planned:{community.slug}"
    last = _state(s, key)
    # Latest date whose due time has passed.
    latest = local_date_of(now)
    while due_at(latest, settings) > now:
        latest -= timedelta(days=1)
    if last is None:
        # First start: no historic backfill; scheduling begins with the next due date.
        _set_state(s, key, latest.isoformat())
        s.add(m.SchedulerEvent(kind="scheduler_initialised", at=now,
                               detail={"community": community.slug, "first_planned_date": (latest + timedelta(days=1)).isoformat()}))
        return []
    start = date.fromisoformat(last) + timedelta(days=1)
    created = []
    d = start
    while d <= latest:
        due = due_at(d, settings)
        late = now - due
        if late > timedelta(days=settings.catchup_max_days):
            s.add(m.SchedulerEvent(kind="expired_run", at=now, detail={"community": community.slug, "date": d.isoformat(),
                                                                         "due_at": iso(due)}))
        else:
            trigger = "scheduled"
            if late > LATE_TOLERANCE:
                trigger = "catchup"
                s.add(m.SchedulerEvent(kind="missed_run", at=now, detail={
                    "community": community.slug, "date": d.isoformat(), "due_at": iso(due),
                    "late_by_minutes": round(late.total_seconds() / 60)}))
            job, new = jobs.enqueue(s, "daily_report", f"daily_report:{community.slug}:{d.isoformat()}",
                                    {"community_id": community.id, "date": d.isoformat(), "trigger": trigger}, now,
                                    priority=5)
            if new:
                created.append(job)
        d += timedelta(days=1)
    if latest >= start:
        _set_state(s, key, latest.isoformat())
    return created


def deliver_outbox(s: Session, now: datetime) -> int:
    """Deliver pending in-app notifications. Other channels are blocked until configured and authorized.
    ``unknown`` outcomes are never retried automatically."""
    if is_paused(s):
        return 0
    n = 0
    for msg in s.scalars(select(m.OutboxMessage).where(m.OutboxMessage.state.in_(("pending", "failed")))):
        msg.attempts += 1
        if msg.channel == "in_app":
            msg.state, msg.sent_at = "sent", now
            n += 1
        else:
            msg.state, msg.last_error = "blocked", "channel not configured or not authorized in this phase"
    return n


def handle(s: Session, job: m.Job, now: datetime, settings: Settings) -> None:
    if job.kind == "daily_report":
        c = s.get(m.Community, job.payload["community_id"])
        if c is None:
            raise ValueError("community no longer exists")
        d = date.fromisoformat(job.payload["date"])
        issue_report(s, c, d, d, now, settings, trigger=job.payload.get("trigger", "scheduled"))
    elif job.kind == "public_sync":
        _public_sync(s, now, settings)
    else:
        raise ValueError(f"unknown job kind {job.kind}")


PUBLIC_REFRESH_HOURS = 6


def _public_sync(s: Session, now: datetime, settings: Settings) -> None:
    from app.connectors.importer import ingest_bundle
    from app.connectors.public_skool import DEFAULT_SOURCES, PublicReadConnector
    con = PublicReadConnector(settings)
    for src in DEFAULT_SOURCES:
        ingest_bundle(s, con.fetch_bundle(src, now), Mode.PUBLIC, now)


def plan_public_refresh(s: Session, now: datetime) -> None:
    """Conservative refresh: at most one public read job per 6-hour window."""
    window = f"{now:%Y%m%d}-{now.hour // PUBLIC_REFRESH_HOURS}"
    jobs.enqueue(s, "public_sync", f"public_sync:{window}", {}, now, priority=7, max_attempts=1)


def tick(mode: Mode, clock: Clock, settings: Settings | None = None, owner: str | None = None, max_jobs: int = 50) -> dict:
    """One worker iteration: heartbeat, plan, run due jobs, deliver outbox."""
    settings = settings or get_settings()
    owner = owner or f"{socket.gethostname()}:{os.getpid()}"
    eng = get_engine(mode, settings)
    now = clock.now()
    ran = 0
    with session_scope(eng) as s:
        _set_state(s, "worker_heartbeat", iso(now))
        for c in s.scalars(select(m.Community).where(m.Community.expected_sources.is_not(None))):
            plan_daily_reports(s, c, now, settings)
        if mode is Mode.PUBLIC and not is_paused(s):
            plan_public_refresh(s, now)
    for _ in range(max_jobs):
        with session_scope(eng) as s:
            job = jobs.claim(s, owner, now)
            if job is None:
                break
            job_id = job.id
        try:
            with session_scope(eng) as s:
                job = s.get(m.Job, job_id)
                assert job is not None
                handle(s, job, now, settings)
                jobs.complete(s, job, now)
            ran += 1
        except Exception as exc:  # recorded on the job; never silently swallowed
            log.exception("job %s failed", job_id)
            with session_scope(eng) as s:
                failed = s.get(m.Job, job_id)
                if failed is not None:
                    jobs.fail(s, failed, now, repr(exc))
    with session_scope(eng) as s:
        delivered = deliver_outbox(s, now)
    return {"ran": ran, "delivered": delivered, "at": iso(now)}


def run_forever(modes: list[Mode], interval_s: float = 30.0) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from app.bootstrap import init_db
    for mode in modes:
        init_db(mode)
    clock = Clock()
    log.info("worker started for modes=%s", [x.value for x in modes])
    while True:
        for mode in modes:
            try:
                log.info("tick %s %s", mode.value, tick(mode, clock))
            except Exception:
                log.exception("tick failed for %s", mode.value)
        _time.sleep(interval_s)
