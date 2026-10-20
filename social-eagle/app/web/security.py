"""Local admin authentication and request hygiene.

* First run creates a random admin token in ``data/admin_token`` (mode 600). No default credentials.
* Login exchanges the token for an HMAC-signed, HttpOnly, SameSite=Strict session cookie.
* Host header must be loopback; state-changing requests must be same-origin.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse, RedirectResponse

COOKIE = "se_session"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "testserver"}
OPEN_PATHS = ("/login", "/healthz", "/static")


def _secret_file(data_dir: Path, name: str) -> Path:
    return data_dir / name


def ensure_admin_token(data_dir: Path) -> tuple[str, bool]:
    data_dir.mkdir(parents=True, exist_ok=True)
    p = _secret_file(data_dir, "admin_token")
    if p.exists():
        return p.read_text().strip(), False
    tok = secrets.token_urlsafe(24)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(tok)
    return tok, True


def _key(data_dir: Path) -> bytes:
    p = _secret_file(data_dir, "session_key")
    if not p.exists():
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    return p.read_text().strip().encode()


def make_session(data_dir: Path, ttl_s: int = 12 * 3600) -> str:
    exp = str(int(time.time()) + ttl_s)
    sig = hmac.new(_key(data_dir), exp.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def valid_session(data_dir: Path, value: str | None) -> bool:
    if not value or "." not in value:
        return False
    exp, sig = value.split(".", 1)
    good = hmac.new(_key(data_dir), exp.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good) and exp.isdigit() and int(exp) > time.time()


def check_token(data_dir: Path, supplied: str) -> bool:
    tok, _ = ensure_admin_token(data_dir)
    return hmac.compare_digest(tok, supplied.strip())


class LocalOnlyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, data_dir: Path):
        super().__init__(app)
        self.data_dir = data_dir

    async def dispatch(self, request: Request, call_next):
        host = (request.headers.get("host") or "").split(":")[0]
        if host not in ALLOWED_HOSTS:
            return PlainTextResponse("Host not allowed (loopback only).", status_code=400)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and (origin.split("://", 1)[-1].split(":")[0] not in ALLOWED_HOSTS):
                return PlainTextResponse("Cross-origin request refused.", status_code=403)
        if not request.url.path.startswith(OPEN_PATHS) and not valid_session(self.data_dir, request.cookies.get(COOKIE)):
            if request.url.path.startswith("/api/"):
                return PlainTextResponse("authentication required", status_code=401)
            return RedirectResponse("/login", status_code=303)
        resp = await call_next(request)
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'"
        # same-origin (not no-referrer): with no-referrer Chrome sends "Origin: null" on form posts,
        # which the origin check above must reject.
        resp.headers["Referrer-Policy"] = "same-origin"
        return resp
