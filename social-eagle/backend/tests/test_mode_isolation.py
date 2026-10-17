"""Evaluation mode cannot initialise a live Skool connector, contact Skool, or send external messages —
even with credentials present. Verified with a network spy (no real external calls are attempted)."""
from __future__ import annotations

import socket

import pytest

from app import db
from app.connectors.base import ModeViolation, UnsupportedOperation
from app.connectors.factory import get_adapter, get_store


def test_skool_adapter_refused_in_evaluation_even_with_credentials(seeded, monkeypatch):
    monkeypatch.setenv("SKOOL_API_KEY", "placeholder-not-a-real-key")
    monkeypatch.setenv("SKOOL_COOKIE", "placeholder")
    with pytest.raises(ModeViolation):
        get_adapter("skool")
    from app.connectors.skool import SkoolAdapter
    with pytest.raises(ModeViolation):
        SkoolAdapter(run_mode="evaluation", live_connection_authorized=True)
    with pytest.raises(ModeViolation):
        SkoolAdapter(run_mode="live", live_connection_authorized=False)
    with pytest.raises(UnsupportedOperation):  # even when both flags are set, no live implementation exists
        SkoolAdapter(run_mode="live", live_connection_authorized=True)


def test_non_simulated_action_cannot_execute_in_evaluation(seeded):
    from app.models import Post
    from app.services import actions
    with db.session_scope() as s:
        p = s.query(Post).filter_by(upstream_id="syn-post-scn-unanswered").one()
        a, _ = actions.create_action(s, kind="reply", group_id=p.group_id, target_type="post", target_upstream_id=p.upstream_id,
                                     payload={"body": "hi"}, origin="manual", idempotency_key="t-live")
        a.simulated, a.delivery_target = False, "live"
        a.state, a.approved_by = "queued", "owner"
        s.commit()
        with pytest.raises(ModeViolation):
            actions.execute_action(s, a)


class NetSpy:
    def __init__(self) -> None:
        self.external: list[object] = []

    def install(self, monkeypatch) -> None:
        real = socket.socket.connect

        def connect(sock, address):  # type: ignore[no-untyped-def]
            host = address[0] if isinstance(address, tuple) else str(address)
            if host not in ("127.0.0.1", "::1", "localhost"):
                self.external.append(address)
                raise ConnectionRefusedError(f"network spy blocked external connection to {address}")
            return real(sock, address)

        monkeypatch.setattr(socket.socket, "connect", connect)
        real_gai = socket.getaddrinfo

        def gai(host, *a, **k):  # type: ignore[no-untyped-def]
            if host not in ("127.0.0.1", "::1", "localhost", None):
                self.external.append(("dns", host))
            return real_gai(host, *a, **k)

        monkeypatch.setattr(socket, "getaddrinfo", gai)


def test_full_job_cycle_makes_no_external_connections(seeded, fake_llm, monkeypatch):
    monkeypatch.setenv("SKOOL_API_KEY", "placeholder-not-a-real-key")
    spy = NetSpy()
    spy.install(monkeypatch)
    from datetime import datetime

    from app import clock, worker
    from app.services import jobs
    with db.session_scope() as s:
        clock.freeze(s, datetime(2026, 10, 1, 5, 0))  # 10:30 IST, outside the rule's quiet hours
    st = get_store()
    st.add_post(author_id="syn-mem-scn-samename-a", title="Reels opening?", body="How should I open my reels in the first three seconds?")
    with db.session_scope() as s:
        jobs.enqueue(s, "sync", "sync:test", {})
        s.commit()
    for _ in range(12):
        with db.session_scope() as s:
            job = jobs.lease(s, "test-worker", 60)
            if job is None:
                break
            worker.run_job(s, job)
    assert spy.external == [], f"external network access attempted: {spy.external}"
    log = st.write_log()
    assert log and all(w["outcome"] in ("sent", "deduplicated") for w in log)  # delivered to the local simulator only
