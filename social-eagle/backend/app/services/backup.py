"""Consistent SQLite backups using the sqlite3 online backup API (never a raw file copy of a live DB).

A backup bundle = app database + simulator database (evaluation) + knowledge source manifest, in a
timestamped folder with a SHA-256 manifest. Restore is verified into a SEPARATE directory by default.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import get_settings


def _backup_db(src: Path, dst: Path) -> None:
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    with d:
        s.backup(d)
    d.execute("PRAGMA journal_mode=DELETE")
    d.close()
    s.close()


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def free_mb(path: Path) -> float:
    path.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(path).free / 1e6


def create_backup(label: str = "manual", dest_root: Path | None = None) -> dict[str, Any]:
    s = get_settings()
    root = dest_root or s.effective_backup_dir
    if free_mb(root) < s.min_free_disk_mb:
        raise OSError(f"Not enough free disk space for a backup at {root} (<{s.min_free_disk_mb} MB free)")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = root / f"backup-{stamp}-{label}"
    out.mkdir(parents=True, exist_ok=False)
    files = {}
    for name, src in (("app.db", s.app_db_path), ("simulator.db", s.sim_db_path)):
        if src.exists():
            _backup_db(src, out / name)
            files[name] = {"sha256": _sha(out / name), "bytes": (out / name).stat().st_size}
    con = sqlite3.connect(out / "app.db")
    check = con.execute("PRAGMA integrity_check").fetchone()[0]
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: S608
              for t in ("members", "posts", "actions", "knowledge_docs", "users")}
    con.close()
    manifest = {"created_utc": stamp, "label": label, "run_mode": s.run_mode, "files": files,
                "integrity_check": check, "row_counts": counts, "format": 1}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    try:
        out.chmod(0o700)
    except OSError:
        pass
    return {"path": str(out), **manifest}


def list_backups() -> list[dict[str, Any]]:
    root = get_settings().effective_backup_dir
    if not root.exists():
        return []
    out = []
    for d in sorted(root.glob("backup-*"), reverse=True):
        m = d / "manifest.json"
        if m.exists():
            out.append({"path": str(d), "name": d.name, **json.loads(m.read_text())})
    return out


def verify_and_restore(backup_dir: Path, target_dir: Path) -> dict[str, Any]:
    """Restore a backup into target_dir (must not be the live data dir) and verify checksums + integrity."""
    s = get_settings()
    if target_dir.resolve() == s.data_dir.resolve():
        raise ValueError("Refusing to restore over the live data directory; use scripts/restore with --replace-live")
    manifest = json.loads((backup_dir / "manifest.json").read_text())
    target_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, meta in manifest["files"].items():
        src = backup_dir / name
        if _sha(src) != meta["sha256"]:
            raise ValueError(f"Checksum mismatch for {name}")
        shutil.copy2(src, target_dir / name)
        con = sqlite3.connect(target_dir / name)
        results[name] = con.execute("PRAGMA integrity_check").fetchone()[0]
        con.close()
    con = sqlite3.connect(target_dir / "app.db")
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in manifest["row_counts"]}  # noqa: S608
    con.close()
    return {"target": str(target_dir), "integrity": results, "row_counts": counts,
            "row_counts_match": counts == manifest["row_counts"]}
