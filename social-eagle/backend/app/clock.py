"""Controllable clock. Every scheduling and date-boundary decision goes through `now()`.

State lives in the settings table so the API and worker processes agree:
  {"mode": "offset", "offset_s": <float>}   -> wall time + offset (evaluation default)
  {"mode": "frozen", "frozen_at": "<iso>"}   -> fixed time (tests, deterministic demos)
"""
from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from .db import get_engine
from .timeutil import parse_ts

_lock = threading.Lock()
_cache: tuple[float, dict[str, Any]] | None = None
_CACHE_TTL = 0.5


def wall_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _state() -> dict[str, Any]:
    global _cache
    with _lock:
        if _cache and time.monotonic() - _cache[0] < _CACHE_TTL:
            return _cache[1]
    st: dict[str, Any] = {"mode": "offset", "offset_s": 0.0}
    try:
        with get_engine().connect() as c:
            row = c.execute(text("SELECT value FROM settings WHERE key='clock'")).fetchone()
        if row is not None:
            import json

            st = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    except OperationalError:  # settings table does not exist before the first migration
        st = {"mode": "offset", "offset_s": 0.0}
    with _lock:
        _cache = (time.monotonic(), st)
    return st


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


def now() -> datetime:
    st = _state()
    if st.get("mode") == "frozen" and st.get("frozen_at"):
        return parse_ts(st["frozen_at"])
    return wall_now() + timedelta(seconds=float(st.get("offset_s", 0.0)))


def describe() -> dict[str, Any]:
    st = _state()
    return {"mode": st.get("mode", "offset"), "now": now().isoformat() + "Z", "state": st}


def set_state(session: Any, state: dict[str, Any]) -> None:
    from . import kv

    kv.put(session, "clock", state)
    session.flush()
    invalidate()


def freeze(session: Any, at: datetime) -> None:
    set_state(session, {"mode": "frozen", "frozen_at": at.isoformat()})


def align_to(session: Any, at: datetime) -> None:
    """Make the clock read `at` right now, then keep ticking in real time."""
    set_state(session, {"mode": "offset", "offset_s": (at - wall_now()).total_seconds()})


def advance(session: Any, delta: timedelta) -> datetime:
    st = dict(_state())
    if st.get("mode") == "frozen":
        new = parse_ts(st["frozen_at"]) + delta
        set_state(session, {"mode": "frozen", "frozen_at": new.isoformat()})
    else:
        st["offset_s"] = float(st.get("offset_s", 0.0)) + delta.total_seconds()
        set_state(session, st)
    return now()
