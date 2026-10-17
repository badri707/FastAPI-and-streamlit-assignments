"""Local admin authentication.

- No default credentials. First admin is created via a one-time enrollment token written to
  data/enrollment.token (mode 600) by `scripts/setup` / first start; the token is deleted after use.
- Passwords: scrypt (stdlib). Sessions: random token in an HttpOnly SameSite=Strict cookie; only its
  SHA-256 is stored. CSRF: per-session token required in X-CSRF-Token for every unsafe method.
- Host header allow-list (DNS-rebinding protection) and Origin check for unsafe methods.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from datetime import timedelta
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import clock
from .config import get_settings
from .db import get_db
from .models import User, UserSession

COOKIE = "se_session"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _alg, n, r, p, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


def validate_new_password(pw: str) -> None:
    if len(pw) < 10:
        raise HTTPException(400, "Password must be at least 10 characters")
    if pw.lower() in {"password123", "admin12345", "socialeagle", "0123456789"}:
        raise HTTPException(400, "Password is too common")


def enrollment_path() -> Path:
    return get_settings().data_dir / "enrollment.token"


def ensure_enrollment_token() -> str | None:
    """Create a one-time enrollment token if no admin exists. Returns the token only when newly created."""
    from .db import session_scope

    with session_scope() as s:
        if s.execute(select(User.id)).first() is not None:
            p = enrollment_path()
            if p.exists():
                p.unlink()
            return None
    p = enrollment_path()
    if p.exists():
        return None
    tok = secrets.token_urlsafe(18)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(tok)
    return tok


def check_enrollment_token(tok: str) -> bool:
    p = enrollment_path()
    if not p.exists():
        return False
    return hmac.compare_digest(p.read_text().strip(), tok.strip())


class RateLimiter:
    def __init__(self, limit: int, window_s: float) -> None:
        self.limit, self.window = limit, window_s
        self.hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self.hits.get(key, []) if now - t < self.window]
            if len(hits) >= self.limit:
                raise HTTPException(429, "Too many attempts; wait a minute and try again")
            hits.append(now)
            self.hits[key] = hits


login_limiter = RateLimiter(5, 60)


def create_session(db: Session, user: User) -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    now = clock.wall_now()
    db.add(UserSession(token_hash=hashlib.sha256(raw.encode()).hexdigest(), csrf_token=csrf, user_id=user.id,
                       created_at=now, expires_at=now + timedelta(hours=get_settings().session_ttl_hours)))
    db.commit()
    return raw, csrf


def _session_from_request(request: Request, db: Session) -> UserSession | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    sess = db.execute(select(UserSession).filter_by(token_hash=hashlib.sha256(raw.encode()).hexdigest())).scalar_one_or_none()
    if sess is None or sess.expires_at < clock.wall_now():
        return None
    return sess


def require_admin(request: Request, db: Session = Depends(get_db)) -> User:
    sess = _session_from_request(request, db)
    if sess is None:
        raise HTTPException(401, "Not signed in")
    if request.method not in SAFE_METHODS:
        tok = request.headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(tok, sess.csrf_token):
            raise HTTPException(403, "Missing or invalid CSRF token")
    user = db.get(User, sess.user_id)
    if user is None or user.role != "admin":
        raise HTTPException(403, "Admin access required")
    request.state.csrf = sess.csrf_token
    return user


def current_session(request: Request, db: Session) -> UserSession | None:
    return _session_from_request(request, db)


def host_allowed(host_header: str | None) -> bool:
    if not host_header:
        return False
    host = host_header.rsplit(":", 1)[0] if not host_header.startswith("[") else host_header.split("]")[0] + "]"
    return host in get_settings().allowed_hosts
