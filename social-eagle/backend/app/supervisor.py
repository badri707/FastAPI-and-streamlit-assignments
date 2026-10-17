"""Process supervisor: runs the API server and the single worker, restarts the worker/API if they crash,
and stops both cleanly. One supervisor per data directory (file lock). Used by scripts/start and scripts/stop.
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from .config import get_settings

BACKEND = Path(__file__).resolve().parents[1]
_stop = False


def _on_signal(signum: int, _frame: object) -> None:
    global _stop
    _stop = True


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _rotate(path: Path, max_bytes: int) -> None:
    if path.exists() and path.stat().st_size > max_bytes:
        old = path.with_suffix(path.suffix + ".1")
        if old.exists():
            old.unlink()
        path.rename(old)


def _spawn(name: str, args: list[str], log: Path) -> subprocess.Popen[bytes]:
    _rotate(log, get_settings().log_max_bytes)
    fh = open(log, "ab")  # noqa: SIM115 (owned by the child for its lifetime)
    return subprocess.Popen(args, cwd=BACKEND, stdout=fh, stderr=subprocess.STDOUT, start_new_session=False)  # noqa: S603 (fixed argv: our interpreter + module)


def main() -> int:
    s = get_settings()
    run = s.data_dir / "run"
    logs = s.data_dir / "logs"
    run.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    lock = open(run / "supervisor.lock", "a+")  # noqa: SIM115
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Social Eagle is already running for this data directory.", file=sys.stderr)
        return 3
    if s.host not in ("127.0.0.1", "localhost", "::1"):
        print("Refusing: only loopback binding is allowed in this phase.", file=sys.stderr)
        return 2
    if not port_free(s.host, s.port):
        print(f"Port {s.port} on {s.host} is already in use by another program. Set PORT in .env to a free port.", file=sys.stderr)
        return 4
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    py = sys.executable
    specs = {
        "api": [py, "-m", "uvicorn", "app.main:app", "--host", s.host, "--port", str(s.port), "--no-proxy-headers",
                "--log-level", "info"],
        "worker": [py, "-m", "app.worker"],
    }
    procs = {k: _spawn(k, v, logs / f"{k}.out.log") for k, v in specs.items()}
    restarts: dict[str, list[float]] = {k: [] for k in specs}
    (run / "supervisor.pid").write_text(str(os.getpid()))

    def write_state(status: str) -> None:
        (run / "state.json").write_text(json.dumps({
            "status": status, "supervisor_pid": os.getpid(), "url": f"http://{s.host}:{s.port}/",
            "pids": {k: p.pid for k, p in procs.items()}, "project": str(BACKEND.parent), "updated": time.time(),
        }, indent=2))

    write_state("running")
    while not _stop:
        time.sleep(1)
        for name, p in list(procs.items()):
            if p.poll() is None:
                continue
            code = p.returncode
            if name == "worker" and code == 3:  # another worker holds the lock: do not fight it
                print("worker exited: another worker is running", file=sys.stderr)
                procs.pop(name)
                write_state("running (worker owned by another process)")
                continue
            now = time.time()
            restarts[name] = [t for t in restarts[name] if now - t < 600] + [now]
            if len(restarts[name]) > 5:
                write_state(f"degraded: {name} crashed repeatedly (exit {code}); see data/logs/{name}.out.log")
                continue
            time.sleep(min(30, 2 ** len(restarts[name])))
            procs[name] = _spawn(name, specs[name], logs / f"{name}.out.log")
            write_state("running")
    write_state("stopping")
    for p in procs.values():
        if p.poll() is None:
            p.send_signal(signal.SIGTERM)
    deadline = time.time() + 20
    for p in procs.values():
        try:
            p.wait(timeout=max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            p.kill()
    write_state("stopped")
    (run / "supervisor.pid").unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
