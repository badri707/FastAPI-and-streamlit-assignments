"""Model provider interface and the local Ollama adapter.

- One inference at a time per process (a lock), bounded context (num_ctx), timeouts, bounded retries.
- A circuit breaker opens after N consecutive failures and fails fast until the cooldown passes.
- No cloud provider is configured or silently enabled. Additional providers must implement `LLMProvider`.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from ..config import Settings, get_settings


class AIUnavailable(Exception):
    """The model cannot be used right now (not running, model missing, breaker open, disabled)."""


class AIInvalidOutput(Exception):
    pass


@dataclass
class LLMResult:
    content: str
    data: dict[str, Any] | None
    model: str
    model_digest: str | None
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None


class LLMProvider(Protocol):
    name: str
    model: str

    def health(self) -> dict[str, Any]: ...

    def chat_json(self, messages: list[dict[str, str]], schema: dict[str, Any], *, timeout_s: float | None = None,
                  max_tokens: int = 400) -> LLMResult: ...


class CircuitBreaker:
    def __init__(self, threshold: int, cooldown_s: float) -> None:
        self.threshold, self.cooldown_s = threshold, cooldown_s
        self.failures = 0
        self.opened_at: float | None = None
        self._lock = threading.Lock()

    def check(self) -> None:
        with self._lock:
            if self.opened_at is None:
                return
            if time.monotonic() - self.opened_at >= self.cooldown_s:
                self.opened_at = None  # half-open: allow one trial
                self.failures = self.threshold - 1
                return
            raise AIUnavailable(f"AI circuit breaker open after {self.failures} consecutive failures; retrying after cooldown")

    def success(self) -> None:
        with self._lock:
            self.failures, self.opened_at = 0, None

    def failure(self) -> None:
        with self._lock:
            self.failures += 1
            if self.failures >= self.threshold:
                self.opened_at = time.monotonic()

    def state(self) -> dict[str, Any]:
        return {"open": self.opened_at is not None, "consecutive_failures": self.failures}


class DisabledProvider:
    name = "none"
    model = "none"

    def health(self) -> dict[str, Any]:
        return {"ok": False, "status": "disabled", "detail": "AI provider disabled by configuration (AI_PROVIDER=none)."}

    def chat_json(self, messages: list[dict[str, str]], schema: dict[str, Any], *, timeout_s: float | None = None,
                  max_tokens: int = 400) -> LLMResult:
        raise AIUnavailable("AI provider disabled by configuration")


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self.s = settings
        self.model = settings.ollama_model
        self.breaker = CircuitBreaker(settings.ai_breaker_threshold, settings.ai_breaker_cooldown_s)
        self._lock = threading.Lock()
        self._digest: str | None = None
        self._client = httpx.Client(base_url=settings.ollama_url, transport=transport, trust_env=False)

    def _model_digest(self) -> str | None:
        if self._digest is None:
            try:
                r = self._client.get("/api/tags", timeout=5)
                for m in r.json().get("models", []):
                    if m.get("name", "").split(":")[0] == self.model.split(":")[0]:
                        self._digest = m.get("digest")
            except (httpx.HTTPError, ValueError):
                return None
        return self._digest

    def health(self) -> dict[str, Any]:
        try:
            v = self._client.get("/api/version", timeout=3).json().get("version")
            tags = self._client.get("/api/tags", timeout=3).json().get("models", [])
        except (httpx.HTTPError, ValueError) as e:
            return {"ok": False, "status": "unreachable", "detail": f"Ollama not reachable at {self.s.ollama_url}: {e.__class__.__name__}",
                    "breaker": self.breaker.state()}
        names = [m.get("name", "") for m in tags]
        present = any(n.split(":")[0] == self.model.split(":")[0] for n in names)
        return {"ok": present and not self.breaker.state()["open"], "status": "ok" if present else "model_missing",
                "ollama_version": v, "model": self.model, "model_present": present, "models": names,
                "digest": self._model_digest() if present else None, "breaker": self.breaker.state(),
                "num_ctx": self.s.ai_num_ctx}

    def chat_json(self, messages: list[dict[str, str]], schema: dict[str, Any], *, timeout_s: float | None = None,
                  max_tokens: int = 400) -> LLMResult:
        self.breaker.check()
        body = {"model": self.model, "messages": messages, "stream": False, "think": False, "format": schema,
                "keep_alive": "15m",
                "options": {"temperature": 0.1, "num_ctx": self.s.ai_num_ctx, "num_predict": max_tokens, "seed": 7}}
        last_err: Exception | None = None
        for attempt in range(self.s.ai_max_retries + 1):
            t0 = time.monotonic()
            try:
                with self._lock:  # one inference at a time in this process
                    r = self._client.post("/api/chat", json=body, timeout=timeout_s or self.s.ai_timeout_s)
                if r.status_code == 404:
                    self.breaker.failure()
                    raise AIUnavailable(f"Model {self.model!r} is not installed in Ollama")
                r.raise_for_status()
                payload = r.json()
                content = payload.get("message", {}).get("content", "")
                try:
                    data = json.loads(content)
                    if not isinstance(data, dict):
                        raise ValueError("not an object")
                except ValueError as e:
                    last_err = AIInvalidOutput(f"Model returned invalid JSON: {e}")
                    continue  # bounded retry on malformed structured output
                self.breaker.success()
                return LLMResult(content=content, data=data, model=self.model, model_digest=self._model_digest(),
                                 latency_ms=int((time.monotonic() - t0) * 1000),
                                 prompt_tokens=payload.get("prompt_eval_count"), completion_tokens=payload.get("eval_count"))
            except httpx.TimeoutException as e:
                self.breaker.failure()
                last_err = AIUnavailable(f"Model call timed out after {timeout_s or self.s.ai_timeout_s:.0f}s")
                last_err.__cause__ = e
                break  # do not stack long timeouts
            except httpx.HTTPError as e:
                self.breaker.failure()
                last_err = AIUnavailable(f"Ollama request failed: {e.__class__.__name__}")
                break
        if isinstance(last_err, AIInvalidOutput):
            self.breaker.failure()
        assert last_err is not None
        raise last_err


_provider: LLMProvider | None = None
_plock = threading.Lock()


def get_provider() -> LLMProvider:
    global _provider
    with _plock:
        if _provider is None:
            s = get_settings()
            _provider = OllamaProvider(s) if s.ai_provider == "ollama" else DisabledProvider()
        return _provider


def set_provider(p: LLMProvider | None) -> None:
    """Testing / reconfiguration hook."""
    global _provider
    with _plock:
        _provider = p
