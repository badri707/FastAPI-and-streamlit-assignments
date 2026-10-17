"""Environment and health report (scripts/doctor). Prints only what is needed; never secrets or the environment."""
from __future__ import annotations

import os
import platform
import shutil
import sqlite3
import subprocess
import sys

import httpx

from .config import get_settings
from .supervisor import port_free

OK, WARN, BAD = "ok  ", "WARN", "FAIL"


def _run(cmd: list[str]) -> str | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip() or None  # noqa: S603 (fixed tool names)
    except (OSError, subprocess.SubprocessError):
        return None


def ram_gb() -> float | None:
    if sys.platform == "darwin":
        v = _run(["sysctl", "-n", "hw.memsize"])
        return int(v) / 1e9 if v else None
    try:
        with open("/proc/meminfo") as f:
            return int(f.readline().split()[1]) / 1e6
    except OSError:
        return None


def memory_pressure() -> str | None:
    if sys.platform == "darwin":
        out = _run(["memory_pressure", "-Q"])
        return out.splitlines()[-1] if out else None
    try:
        with open("/proc/meminfo") as f:
            info = {line.split(":")[0]: int(line.split()[1]) for line in f}
        return f"{info['MemAvailable'] / 1e6:.1f} GB available of {info['MemTotal'] / 1e6:.1f} GB"
    except (OSError, KeyError):
        return None


def main(argv: list[str]) -> int:
    brief = "--brief" in argv
    s = get_settings()
    rows: list[tuple[str, str, str]] = []
    add = rows.append
    if not brief:
        mac = _run(["sw_vers", "-productVersion"]) if sys.platform == "darwin" else None
        add((OK, "platform", f"{platform.system()} {mac or platform.release()} {platform.machine()}"))
        r = ram_gb()
        add((OK if r and r >= 7.5 else WARN, "memory", f"{r:.1f} GB RAM" if r else "unknown"))
        mp = memory_pressure()
        if mp:
            add((OK, "memory pressure", mp))
        add((OK if sys.version_info[:2] == (3, 12) else WARN, "python", platform.python_version()))
        for tool in ("node", "npm", "uv", "ollama"):
            p = shutil.which(tool)
            add((OK if p else (WARN if tool == "ollama" else BAD), tool, (_run([tool, "--version"]) or "found") if p else "not found"))
    add((OK, "run mode", f"{s.run_mode} (live Skool connection: deferred until approval)"))
    free = shutil.disk_usage(s.data_dir if s.data_dir.exists() else s.data_dir.parent).free / 1e6
    add((OK if free > s.min_free_disk_mb else BAD, "disk", f"{free:,.0f} MB free at {s.data_dir}"))
    if s.app_db_path.exists():
        try:
            con = sqlite3.connect(f"file:{s.app_db_path}?mode=ro", uri=True)
            ver = con.execute("SELECT version_num FROM alembic_version").fetchone()
            members = con.execute("SELECT COUNT(*) FROM members").fetchone()[0]
            hb = con.execute("SELECT status, wall_beat_at FROM worker_heartbeats ORDER BY wall_beat_at DESC LIMIT 1").fetchone()
            con.close()
            add((OK, "database", f"migrated to {ver[0] if ver else '?'}; {members:,} members"))
            add((OK if hb else WARN, "worker", f"last status {hb[0]} at {hb[1]} UTC" if hb else "never ran"))
        except sqlite3.Error as e:
            add((BAD, "database", f"unreadable: {e}"))
    else:
        add((WARN, "database", "not created yet (run scripts/setup)"))
    running = not port_free(s.host, s.port)
    add((OK, "port", f"{s.host}:{s.port} {'in use (app running?)' if running else 'free'}"))
    try:
        with httpx.Client(base_url=s.ollama_url, trust_env=False, timeout=3) as c:
            v = c.get("/api/version").json().get("version")
            names = [m["name"] for m in c.get("/api/tags").json().get("models", [])]
        present = any(n.split(":")[0] == s.ollama_model.split(":")[0] for n in names)
        add((OK if present else WARN, "local AI", f"Ollama {v}; model {s.ollama_model} {'present' if present else 'MISSING — AI features will show unavailable'}"))
    except (httpx.HTTPError, ValueError):
        add((WARN, "local AI", f"Ollama not reachable at {s.ollama_url}. App still runs; AI features show 'unavailable'."))
    if s.external_ssd_path:
        add((OK if s.external_ssd_path.exists() else WARN, "external SSD", f"{s.external_ssd_path} {'present' if s.external_ssd_path.exists() else 'absent (optional; not required to start)'}"))
    if "SKOOL" in " ".join(os.environ) and s.run_mode == "evaluation":
        add((OK, "skool credentials", "present in environment but IGNORED in evaluation mode"))
    width = max(len(r[1]) for r in rows)
    for status, name, detail in rows:
        print(f"[{status}] {name.ljust(width)}  {detail}")
    return 1 if any(r[0] == BAD for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
