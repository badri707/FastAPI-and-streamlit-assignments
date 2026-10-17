"""Connector construction. RUN_MODE is enforced here, in the backend, not in the UI."""
from __future__ import annotations

from functools import lru_cache

from ..config import Settings, get_settings
from .base import CommunityAdapter, ModeViolation
from .simulator import SimulatorAdapter, SimulatorStore


def _clock():  # late import avoids a cycle at module import time
    from .. import clock

    return clock.now()


@lru_cache
def simulator_store(path: str) -> SimulatorStore:
    from pathlib import Path

    return SimulatorStore(Path(path), _clock)


def get_store(settings: Settings | None = None) -> SimulatorStore:
    s = settings or get_settings()
    if s.run_mode != "evaluation":
        raise ModeViolation("The local simulator exists only in evaluation mode")
    return simulator_store(str(s.sim_db_path))


def get_adapter(source: str = "simulator", settings: Settings | None = None) -> CommunityAdapter:
    s = settings or get_settings()
    if s.run_mode == "evaluation":
        if source != "simulator":
            raise ModeViolation(f"Evaluation mode only permits the local simulator (requested {source!r})")
        return SimulatorAdapter(get_store(s))
    # Live mode: the Skool adapter refuses construction until authorized AND implemented.
    if source == "skool":
        from .skool import SkoolAdapter

        return SkoolAdapter(run_mode=s.run_mode, live_connection_authorized=s.live_connection_authorized)
    raise ModeViolation(f"Source {source!r} is not available in run mode {s.run_mode!r}")


def delivery_target(settings: Settings | None = None) -> str:
    s = settings or get_settings()
    return "local-simulator" if s.run_mode == "evaluation" else "live"
