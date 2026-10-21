"""Command line: python -m app.cli <command>."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import socket
import sqlite3
import sys
from datetime import date
from pathlib import Path

from app.config import Mode, get_settings


def _settings():
    return get_settings()


def cmd_init(_a) -> int:
    from app.bootstrap import init_db
    from app.web.security import ensure_admin_token
    st = _settings()
    for mode in (Mode.PUBLIC, Mode.TEST):
        init_db(mode, st)
    tok, created = ensure_admin_token(st.data_dir)
    print(f"Databases migrated in {st.data_dir}")
    print("Admin token created: " + tok if created else f"Admin token already exists in {st.data_dir / 'admin_token'}")
    return 0


def _test_db_paths(st) -> list[Path]:
    p = st.db_path(Mode.TEST)
    assert p.name == "test.db", "refusing: evaluation commands only target the synthetic test database"
    return [p, p.with_name("test.db-wal"), p.with_name("test.db-shm")]


def cmd_reset_evaluation(a) -> int:
    st = _settings()
    if not a.yes:
        print("This DISCARDS the synthetic test workspace (data/test.db and its reports). "
              "Public data is not touched. Re-run with --yes to confirm.")
        return 2
    from app.db import reset_engines
    reset_engines()
    for p in _test_db_paths(st):
        p.unlink(missing_ok=True)
    shutil.rmtree(st.reports_dir / "social-eagle-synthetic", ignore_errors=True)
    print("Synthetic test workspace removed.")
    return 0


def _has_data(p: Path) -> bool:
    with sqlite3.connect(p) as c:
        try:
            return c.execute("SELECT count(*) FROM communities").fetchone()[0] > 0
        except sqlite3.OperationalError:
            return False


def cmd_seed_evaluation(a) -> int:
    """Load the fixed synthetic scenario timeline and issue the demonstration reports at their historical times."""
    from app import fixtures as fx
    from app.bootstrap import init_db
    from app.connectors.importer import ingest_bundle
    from app.db import get_engine, session_scope
    from app.reports.daily import issue_report
    st = _settings()
    if st.db_path(Mode.TEST).exists() and _has_data(st.db_path(Mode.TEST)):
        if not a.yes:
            print("A test workspace already exists. Seeding resets it (discarding evaluation changes). Re-run with --yes.")
            return 2
        a_reset = argparse.Namespace(yes=True)
        cmd_reset_evaluation(a_reset)
    init_db(Mode.TEST, st)
    eng = get_engine(Mode.TEST, st)
    from sqlalchemy import select

    from app import models as m
    with session_scope(eng) as s:
        for when, b in fx.initial_steps():
            ingest_bundle(s, fx.clone(b), Mode.TEST, when)

    def report(day: str, at: str, trigger: str):
        with session_scope(eng) as s:
            c = s.scalar(select(m.Community).where(m.Community.slug == fx.SLUG))
            assert c is not None
            d = date.fromisoformat(day)
            rr, _ = issue_report(s, c, d, d, fx.at(at), st, trigger)
            print(f"  report {day} r{rr.revision} {rr.status:<11} ({trigger}) -> {rr.output_dir}")

    def ingest(when: str, b: dict):
        with session_scope(eng) as s:
            ingest_bundle(s, fx.clone(b), Mode.TEST, fx.at(when))

    print("Seeding SYNTHETIC Social Eagle scenarios (fictional data):")
    report("2026-10-19", "2026-10-20 09:00", "scheduled")
    ingest("2026-10-20 12:00", fx.late_delta_bundle())
    report("2026-10-19", "2026-10-20 12:30", "manual")
    d2 = fx.day2_bundles()
    for k in ("membership", "progress", "failed"):
        ingest("2026-10-21 02:00", d2[k])
    report("2026-10-20", "2026-10-21 09:00", "scheduled")
    ingest("2026-10-21 10:00", d2["recovered"])
    report("2026-10-20", "2026-10-21 10:05", "manual")
    for b in fx.total_outage_bundles():
        ingest("2026-10-22 02:00", b)
    report("2026-10-21", "2026-10-22 09:00", "scheduled")
    print("Done. Open the dashboard and choose the 'test' workspace.")
    return 0


def cmd_serve(a) -> int:
    import uvicorn
    st = _settings()
    if st.host not in ("127.0.0.1", "localhost"):
        print("Refusing to bind a non-loopback address in this phase.")
        return 2
    from app.web.main import create_app
    uvicorn.run(create_app(st), host=st.host, port=st.port, log_level="info")
    return 0


def cmd_worker(a) -> int:
    from app.worker.scheduler import run_forever
    modes = [Mode.PUBLIC, Mode.TEST] if a.mode == "all" else [Mode(a.mode)]
    run_forever(modes, interval_s=a.interval)
    return 0


def cmd_tick(a) -> int:
    from app.bootstrap import init_db
    from app.timeutil import Clock
    from app.worker.scheduler import tick
    init_db(Mode(a.mode))
    print(json.dumps(tick(Mode(a.mode), Clock())))
    return 0


def cmd_public_sync(a) -> int:
    from app.bootstrap import init_db
    from app.connectors.importer import ingest_bundle
    from app.connectors.public_skool import DEFAULT_SOURCES, PublicReadConnector
    from app.db import get_engine, session_scope
    from app.timeutil import Clock
    st = _settings()
    init_db(Mode.PUBLIC, st)
    con = PublicReadConnector(st)
    rc = 0
    for src in DEFAULT_SOURCES:
        b = con.fetch_bundle(src, Clock().now())
        with session_scope(get_engine(Mode.PUBLIC, st)) as s:
            run = ingest_bundle(s, b, Mode.PUBLIC, Clock().now())
            print(f"{src.url}: {run.status} new={run.records_new} changed={run.records_changed} error={run.error}")
            rc |= run.status == "failed"
    return rc


def cmd_public_inspect(_a) -> int:
    from app.connectors.public_skool import inspect_cached_page
    print(inspect_cached_page(_settings().data_dir / "public_cache"))
    return 0


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def cmd_backup(a) -> int:
    """Consistent online backup via SQLite's backup API (safe while the app is running)."""
    from app.timeutil import Clock
    st = _settings()
    out_dir = Path(a.out) if a.out else st.data_dir / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = Clock().now().strftime("%Y%m%dT%H%M%SZ")
    for mode in (Mode.PUBLIC, Mode.TEST):
        src = st.db_path(mode)
        if not src.exists():
            continue
        dst = out_dir / f"{mode.value}-{stamp}.db"
        with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
            s.backup(d)
        os.chmod(dst, 0o600)
        (dst.with_suffix(".sha256")).write_text(_sha(dst) + "\n")
        print(f"backup {mode.value}: {dst}")
    return 0


def cmd_restore(a) -> int:
    """Restore a backup into a SEPARATE evaluation directory and verify it. Never overwrites live data."""
    st = _settings()
    src = Path(a.backup)
    target_dir = Path(a.to) if a.to else st.data_dir / "restore-eval"
    target_dir.mkdir(parents=True, exist_ok=True)
    dst = target_dir / src.name
    for live in (st.db_path(Mode.PUBLIC), st.db_path(Mode.TEST)):
        if dst.resolve() == live.resolve():
            print("Refusing to restore over a live database.")
            return 2
    sha_file = src.with_suffix(".sha256")
    if sha_file.exists() and sha_file.read_text().strip() != _sha(src):
        print("Checksum mismatch — backup file changed or is corrupt.")
        return 1
    with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
        s.backup(d)
    with sqlite3.connect(dst) as d:
        ok = d.execute("PRAGMA integrity_check").fetchone()[0]
        counts = {t: d.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                  for t in ("members", "posts", "report_runs", "sync_runs")}
    print(json.dumps({"restored_to": str(dst), "integrity": ok, "counts": counts}))
    return 0 if ok == "ok" else 1


def cmd_doctor(a) -> int:
    st = _settings()
    checks: dict[str, object] = {"python": sys.version.split()[0], "machine": platform.machine(), "system": platform.system()}
    try:
        total, used, free = shutil.disk_usage(st.data_dir if st.data_dir.exists() else Path.cwd())
        checks["disk_free_gb"] = round(free / 1e9, 1)
    except OSError as exc:
        checks["disk_free_gb"] = f"error {exc}"
    try:
        import os as _os
        checks["ram_gb"] = round(_os.sysconf("SC_PAGE_SIZE") * _os.sysconf("SC_PHYS_PAGES") / 1e9, 1)
    except (ValueError, OSError, AttributeError):
        checks["ram_gb"] = "unknown"
    with socket.socket() as sck:
        checks[f"port_{st.port}"] = "in use" if sck.connect_ex(("127.0.0.1", st.port)) == 0 else "free"
    with socket.socket() as sck:
        sck.settimeout(0.5)
        checks["ollama_localhost_11434"] = "reachable" if sck.connect_ex(("127.0.0.1", 11434)) == 0 else "not running"
    ext = os.environ.get("SE_EXTERNAL_DIR")
    checks["external_ssd"] = ("not configured (optional)" if not ext else
                              ("mounted" if Path(ext).is_dir() else "configured but missing — app runs without it"))
    for mode in (Mode.PUBLIC, Mode.TEST):
        p = st.db_path(mode)
        if p.exists():
            with sqlite3.connect(p) as c:
                checks[f"db_{mode.value}"] = c.execute("PRAGMA integrity_check").fetchone()[0] + \
                    " / journal=" + c.execute("PRAGMA journal_mode").fetchone()[0]
        else:
            checks[f"db_{mode.value}"] = "not created yet"
    checks["private_mode"] = "deferred (disabled)"
    for k, v in checks.items():
        print(f"{k:<24} {v}")
    if isinstance(checks["disk_free_gb"], float) and checks["disk_free_gb"] < 2:
        print("WARNING: less than 2 GB free disk space")
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    for name, fn in (("seed-evaluation", cmd_seed_evaluation), ("reset-evaluation", cmd_reset_evaluation)):
        p = sub.add_parser(name)
        p.add_argument("--yes", action="store_true")
        p.set_defaults(fn=fn)
    sub.add_parser("serve").set_defaults(fn=cmd_serve)
    p = sub.add_parser("worker")
    p.add_argument("--mode", default="all", choices=["all", "public", "test"])
    p.add_argument("--interval", type=float, default=30.0)
    p.set_defaults(fn=cmd_worker)
    p = sub.add_parser("tick")
    p.add_argument("--mode", default="test", choices=["public", "test"])
    p.set_defaults(fn=cmd_tick)
    sub.add_parser("public-sync").set_defaults(fn=cmd_public_sync)
    sub.add_parser("public-inspect").set_defaults(fn=cmd_public_inspect)
    p = sub.add_parser("backup")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_backup)
    p = sub.add_parser("restore")
    p.add_argument("backup")
    p.add_argument("--to")
    p.set_defaults(fn=cmd_restore)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
