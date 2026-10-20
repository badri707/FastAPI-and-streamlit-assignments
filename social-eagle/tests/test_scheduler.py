from __future__ import annotations

from sqlalchemy import func, select

from app import fixtures as fx
from app import models as m
from app.config import Mode
from app.db import session_scope
from app.timeutil import FrozenClock
from app.worker import jobs
from app.worker.scheduler import set_paused, tick


def count(engine, model, *where):
    with session_scope(engine) as s:
        return s.scalar(select(func.count()).select_from(model).where(*where))


def test_scheduled_report_runs_once_and_survives_restart(seeded, settings):
    clock = FrozenClock(fx.at("2026-10-20 08:59"))
    assert tick(Mode.TEST, clock, settings)["ran"] == 0  # not due yet (due 09:00 IST for 10-19)
    clock.at = fx.at("2026-10-20 09:01")
    r = tick(Mode.TEST, clock, settings)
    assert r["ran"] == 1 and r["delivered"] == 1
    # "restart": new worker identity, same DB → nothing duplicated
    clock.advance(minutes=5)
    assert tick(Mode.TEST, clock, settings, owner="other-worker")["ran"] == 0
    assert count(seeded, m.ReportRun) == 1
    with session_scope(seeded) as s:
        rr = s.scalar(select(m.ReportRun))
        assert (rr.report_date, rr.trigger, rr.status) == ("2026-10-19", "scheduled", "complete")
        assert s.scalar(select(m.OutboxMessage)).state == "sent"


def test_sleep_wake_catchup_and_missed_runs(seeded, settings):
    tick(Mode.TEST, FrozenClock(fx.at("2026-10-20 08:00")), settings)
    clock = FrozenClock(fx.at("2026-10-20 09:01"))
    tick(Mode.TEST, clock, settings)
    clock.at = fx.at("2026-10-23 10:30")  # laptop asleep for three days
    r = tick(Mode.TEST, clock, settings)
    assert r["ran"] == 3
    with session_scope(seeded) as s:
        rows = s.scalars(select(m.ReportRun).order_by(m.ReportRun.report_date)).all()
        assert [(x.report_date, x.trigger) for x in rows] == [
            ("2026-10-19", "scheduled"), ("2026-10-20", "catchup"), ("2026-10-21", "catchup"), ("2026-10-22", "catchup")]
        # no source covered those days → unavailable, never fabricated zero activity
        assert {x.status for x in rows[1:]} == {"unavailable"}
        missed = s.scalars(select(m.SchedulerEvent).where(m.SchedulerEvent.kind == "missed_run")).all()
        assert sorted(e.detail["date"] for e in missed) == ["2026-10-20", "2026-10-21", "2026-10-22"]
    tick(Mode.TEST, clock, settings)
    assert count(seeded, m.ReportRun) == 4


def test_old_missed_days_expire_instead_of_bursting(seeded, settings):
    tick(Mode.TEST, FrozenClock(fx.at("2026-10-20 08:00")), settings)
    clock = FrozenClock(fx.at("2026-10-20 09:01"))
    tick(Mode.TEST, clock, settings)
    clock.at = fx.at("2026-11-05 09:30")
    tick(Mode.TEST, clock, settings)
    with session_scope(seeded) as s:
        expired = s.scalar(select(func.count()).select_from(m.SchedulerEvent).where(m.SchedulerEvent.kind == "expired_run"))
        generated = s.scalar(select(func.count()).select_from(m.ReportRun))
    assert expired > 0 and generated == 1 + (16 - expired)


def test_two_workers_cannot_claim_same_job(engine, settings):
    now = fx.at("2026-10-20 09:00")
    with session_scope(engine) as s:
        jobs.enqueue(s, "noop", "k1", {}, now)
        _, created = jobs.enqueue(s, "noop", "k1", {}, now)
        assert not created
    with session_scope(engine) as s:
        a = jobs.claim(s, "w1", now)
    with session_scope(engine) as s:
        b = jobs.claim(s, "w2", now)
    assert a is not None and b is None
    # crashed worker: lease expires, job is recovered rather than lost
    with session_scope(engine) as s:
        c = jobs.claim(s, "w2", fx.at("2026-10-20 09:10"))
        assert c is not None and c.attempts == 2


def test_failed_job_is_visible_not_swallowed(engine, settings):
    now = fx.at("2026-10-20 09:00")
    with session_scope(engine) as s:
        jobs.enqueue(s, "unknown_kind", "bad", {}, now, max_attempts=1)
    tick(Mode.TEST, FrozenClock(now), settings)
    with session_scope(engine) as s:
        j = s.scalar(select(m.Job).where(m.Job.dedupe_key == "bad"))
        assert j.status == "failed" and "unknown job kind" in j.last_error


def test_pause_holds_delivery(seeded, settings):
    tick(Mode.TEST, FrozenClock(fx.at("2026-10-20 08:00")), settings)
    with session_scope(seeded) as s:
        set_paused(s, True)
    tick(Mode.TEST, FrozenClock(fx.at("2026-10-20 09:01")), settings)
    with session_scope(seeded) as s:
        assert s.scalar(select(m.OutboxMessage)).state == "pending"
        set_paused(s, False)
    tick(Mode.TEST, FrozenClock(fx.at("2026-10-20 09:02")), settings)
    with session_scope(seeded) as s:
        msg = s.scalar(select(m.OutboxMessage))
        assert msg.state == "sent" and msg.attempts == 1
