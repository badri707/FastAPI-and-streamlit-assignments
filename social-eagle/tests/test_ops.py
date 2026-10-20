from __future__ import annotations

import sqlite3

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select

from app import fixtures as fx
from app import models as m
from app.bootstrap import init_db
from app.cli import main as cli
from app.config import Mode
from app.connectors import public_skool
from app.db import get_engine, session_scope
from app.timeutil import FrozenClock
from app.worker.scheduler import tick


def test_migrations_match_models(settings):
    eng = get_engine(Mode.TEST, settings)
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), m.Base.metadata)
    assert diff == []
    assert command  # alembic importable


def test_backup_and_restore_into_separate_location(seeded, settings, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SE_DATA_DIR", str(settings.data_dir))
    assert cli(["backup", "--out", str(tmp_path / "bk")]) == 0
    backup = next((tmp_path / "bk").glob("test-*.db"))
    live_before = settings.db_path(Mode.TEST).stat().st_mtime_ns
    assert cli(["restore", str(backup), "--to", str(tmp_path / "eval")]) == 0
    out = capsys.readouterr().out
    assert '"integrity": "ok"' in out
    with sqlite3.connect(tmp_path / "eval" / backup.name) as c:
        assert c.execute("select count(*) from members").fetchone()[0] == 15
    assert settings.db_path(Mode.TEST).stat().st_mtime_ns == live_before  # live data untouched
    backup.write_bytes(backup.read_bytes() + b"x")
    assert cli(["restore", str(backup), "--to", str(tmp_path / "eval2")]) == 1  # checksum mismatch detected


def test_seed_evaluation_refuses_without_confirmation(seeded, settings, monkeypatch):
    monkeypatch.setenv("SE_DATA_DIR", str(settings.data_dir))
    assert cli(["seed-evaluation"]) == 2
    assert cli(["reset-evaluation"]) == 2


def test_public_refresh_failure_is_recorded_not_empty(settings, monkeypatch):
    init_db(Mode.PUBLIC, settings)
    monkeypatch.setattr(public_skool.PublicReadConnector, "fetch_bundle",
                        lambda self, src, now: public_skool.failed_bundle(src, now, "AccessDenied: proxy 403 (simulated)"))
    tick(Mode.PUBLIC, FrozenClock(fx.at("2026-10-20 10:00")), settings)
    tick(Mode.PUBLIC, FrozenClock(fx.at("2026-10-20 10:30")), settings)  # same 6h window: no second read
    with session_scope(get_engine(Mode.PUBLIC, settings)) as s:
        runs = s.scalars(select(m.SyncRun)).all()
        assert [(r.status, r.source_name) for r in runs] == [("failed", "public_feed")]
        assert s.scalar(select(m.Post)) is None
