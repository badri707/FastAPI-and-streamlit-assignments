from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..models import User, UserSession
from ..security import (
    COOKIE,
    check_enrollment_token,
    create_session,
    current_session,
    enrollment_path,
    hash_password,
    login_limiter,
    require_admin,
    validate_new_password,
    verify_password,
)
from ..services import notify

router = APIRouter(prefix="/api/auth", tags=["auth"])


class EnrollIn(BaseModel):
    token: str = Field(min_length=8, max_length=200)
    username: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=200)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)


def _set_cookie(resp: Response, raw: str) -> None:
    resp.set_cookie(COOKIE, raw, httponly=True, samesite="strict", secure=False, path="/", max_age=12 * 3600)


@router.get("/status")
def status(request: Request, db: Session = Depends(get_db)) -> dict:
    has_user = db.execute(select(User.id)).first() is not None
    sess = current_session(request, db)
    user = db.get(User, sess.user_id) if sess else None
    return {"enrolled": has_user, "enrollment_pending": (not has_user) and enrollment_path().exists(),
            "signed_in": user is not None, "username": user.username if user else None,
            "csrf": sess.csrf_token if sess else None}


@router.post("/enroll")
def enroll(body: EnrollIn, response: Response, db: Session = Depends(get_db)) -> dict:
    if db.execute(select(User.id)).first() is not None:
        raise HTTPException(409, "An admin already exists; enrollment is closed")
    login_limiter.check("enroll")
    if not check_enrollment_token(body.token):
        raise HTTPException(403, "Invalid enrollment token")
    validate_new_password(body.password)
    user = User(username=body.username, password_hash=hash_password(body.password), role="admin", created_at=clock.wall_now())
    db.add(user)
    notify.audit(db, body.username, "auth.enrolled")
    db.commit()
    enrollment_path().unlink(missing_ok=True)
    raw, csrf = create_session(db, user)
    _set_cookie(response, raw)
    return {"ok": True, "username": user.username, "csrf": csrf}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    login_limiter.check(f"{request.client.host if request.client else '?'}:{body.username}")
    user = db.execute(select(User).filter_by(username=body.username)).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid username or password")
    raw, csrf = create_session(db, user)
    _set_cookie(response, raw)
    notify.audit(db, user.username, "auth.login")
    db.commit()
    return {"ok": True, "username": user.username, "csrf": csrf}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict:
    sess = current_session(request, db)
    if sess is not None:
        db.delete(sess)
        db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


class PasswordIn(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(min_length=10, max_length=200)


@router.post("/password")
def change_password(body: PasswordIn, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict:
    if not verify_password(body.current, user.password_hash):
        raise HTTPException(403, "Current password is incorrect")
    validate_new_password(body.new)
    user.password_hash = hash_password(body.new)
    db.query(UserSession).filter(UserSession.user_id == user.id).delete()
    notify.audit(db, user.username, "auth.password_changed")
    db.commit()
    return {"ok": True, "note": "All sessions signed out; sign in again."}
