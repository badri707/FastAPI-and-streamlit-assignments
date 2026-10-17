"""Shared fixtures. Every test runs against a temporary data directory with RUN_MODE=evaluation and a frozen clock.

The FakeLLM below is a TEST DOUBLE used to make pipeline/policy tests deterministic. It is never used by the
application at runtime and is not evidence of AI quality — see tests/ai_eval for the real-model evaluation.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def _configure_env(data_dir: Path, **extra: str) -> None:
    os.environ.update({
        "DATA_DIR": str(data_dir), "RUN_MODE": "evaluation", "CLOCK_MODE": "frozen",
        "ALLOWED_HOSTS": '["127.0.0.1","localhost","testserver"]', "AI_PROVIDER": "ollama",
        "LIVE_CONNECTION_AUTHORIZED": "false", **extra,
    })
    from app import clock, db
    from app.ai import provider
    from app.config import get_settings
    from app.connectors.factory import simulator_store

    get_settings.cache_clear()
    simulator_store.cache_clear()
    provider.set_provider(None)
    db.configure(get_settings().app_db_path)
    clock.invalidate()


class FakeLLM:
    """Deterministic stand-in for the model (TEST DOUBLE). Answers with the first source's first sentence."""

    name = "fake"
    model = "fake-test-double"

    def __init__(self, mode: str = "cite_first", fail: Exception | None = None) -> None:
        self.mode = mode
        self.fail = fail
        self.calls: list[list[dict[str, str]]] = []

    def health(self) -> dict[str, Any]:
        return {"ok": True, "status": "ok", "model": self.model}

    def chat_json(self, messages: list[dict[str, str]], schema: dict[str, Any], *, timeout_s: float | None = None,
                  max_tokens: int = 400) -> Any:
        from app.ai.provider import LLMResult

        self.calls.append(messages)
        if self.fail:
            raise self.fail
        user = messages[-1]["content"]
        props = schema.get("properties", {})
        if "tool" in props:  # owner chat router
            data: dict[str, Any] = {"tool": "overview", "days": 30}
        elif "summary" in props:
            data = {"summary": "Members ask about reels.", "suggested_faq": "How do I open a reel?"}
        elif set(props) == {"answer"}:
            nums = re.findall(r'"active_members": (\d+)', user)
            data = {"answer": f"There are {nums[0]} active members." if nums else "Here is the summary."}
        else:
            m = re.search(r"\[S1\][^\n]*\n([^\n]+)", user)
            first = (m.group(1).split(". ")[0] if m else "").strip()
            if self.mode == "abstain" or not first:
                data = {"status": "abstain", "answer": "", "citations": []}
            elif self.mode == "invent_number":
                data = {"status": "answered", "answer": "Wait exactly 9999 days [S1].", "citations": ["S1"]}
            elif self.mode == "bad_citation":
                data = {"status": "answered", "answer": f"{first} [S9].", "citations": ["S9"]}
            elif self.mode == "pii":
                data = {"status": "answered", "answer": "Contact jane.doe@example.com [S1].", "citations": ["S1"]}
            else:
                data = {"status": "answered", "answer": f"{first}. [S1]", "citations": ["S1"]}
        return LLMResult(content=json.dumps(data), data=data, model=self.model, model_digest="sha256:test",
                         latency_ms=1, prompt_tokens=10, completion_tokens=10)


@pytest.fixture
def fresh(tmp_path: Path) -> Iterator[Path]:
    """Empty, migrated evaluation database (no seed)."""
    _configure_env(tmp_path)
    from app.config import get_settings
    from app.migrate import upgrade

    upgrade(get_settings().app_db_path)
    yield tmp_path


@pytest.fixture(scope="session")
def seeded_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One 250-member seed per test session, copied for each test that needs it (fast and isolated)."""
    d = tmp_path_factory.mktemp("seed-template")
    _configure_env(d)
    from app.evaluation import reset_evaluation

    reset_evaluation(members=250)
    from app import db

    db.get_engine().dispose()
    return d


@pytest.fixture
def seeded(seeded_template: Path, tmp_path: Path) -> Iterator[Path]:
    import sqlite3

    for name in ("app.db", "simulator.db"):
        src = sqlite3.connect(seeded_template / name)
        dst = sqlite3.connect(tmp_path / name)
        src.backup(dst)
        src.close()
        dst.close()
    _configure_env(tmp_path)
    yield tmp_path


@pytest.fixture
def fake_llm() -> Iterator[FakeLLM]:
    from app.ai import provider

    f = FakeLLM()
    provider.set_provider(f)  # type: ignore[arg-type]
    yield f
    provider.set_provider(None)


@pytest.fixture
def client(seeded: Path) -> Iterator[Any]:
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.security import ensure_enrollment_token, login_limiter

    login_limiter.hits.clear()  # the limiter is per-process; tests enroll repeatedly

    app = create_app()
    with TestClient(app) as c:
        ensure_enrollment_token()
        tok = (seeded / "enrollment.token").read_text()
        r = c.post("/api/auth/enroll", json={"token": tok, "username": "owner", "password": "a-long-test-password"})
        assert r.status_code == 200, r.text
        c.headers["x-csrf-token"] = r.json()["csrf"]
        yield c


def session():  # convenience for tests
    from app import db

    return db.SessionLocal()
