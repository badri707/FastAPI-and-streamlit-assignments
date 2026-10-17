"""Future Skool adapter boundary — DISABLED in this phase.

This module deliberately contains no endpoints, scraping logic or credential handling. The
connection phase starts only after the owner approves the independent application and explicitly
authorizes a live connection. See docs/SKOOL_ADAPTER_PLAN.md for desired fields/actions and the
public-documentation limitations recorded so far.

Construction is refused unless BOTH run_mode == "live" and live_connection_authorized is true, and even
then it raises because no live implementation exists yet. Credentials present in the environment are
never read here.
"""
from __future__ import annotations

from typing import Any, NoReturn

from .base import AdapterInfo, CommunityAdapter, ModeViolation, UnsupportedOperation


class SkoolAdapter(CommunityAdapter):
    def __init__(self, *, run_mode: str, live_connection_authorized: bool) -> None:
        if run_mode != "live":
            raise ModeViolation("Skool adapter cannot be constructed in evaluation mode")
        if not live_connection_authorized:
            raise ModeViolation("Live Skool connection has not been authorized by the owner")
        raise UnsupportedOperation(
            "Live Skool connector is deferred until approval; no implementation exists in this phase"
        )

    info = AdapterInfo(
        source="skool", mode="live", display_name="Skool (deferred until approval)", simulated=False,
        operations={}, coverage_notes=["Not implemented. Deferred until owner approval."],
    )

    def _no(self, *_: Any, **__: Any) -> NoReturn:
        raise UnsupportedOperation("Skool connector deferred until approval")

    health = fetch_changes = list_thread = publish_comment = _no  # type: ignore[assignment]
    send_member_message = apply_member_action = find_by_idempotency_key = _no  # type: ignore[assignment]
