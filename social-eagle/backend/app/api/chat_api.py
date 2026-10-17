from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock, kv
from ..ai import chat
from ..db import get_db
from ..models import ChatMessage
from ..security import require_admin
from ..timeutil import iso

router = APIRouter(prefix="/api/chat", tags=["chat"], dependencies=[Depends(require_admin)])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    conversation_id: str | None = Field(None, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")


@router.post("")
def ask(body: ChatIn, db: Session = Depends(get_db)) -> dict:
    if (kv.get(db, "ai_task_modes") or {}).get("owner_chat") == "disabled":
        raise HTTPException(409, "Owner chat is disabled in settings")
    cid = body.conversation_id or secrets.token_hex(6)
    hist = [{"role": m.role, "content": m.content} for m in db.execute(
        select(ChatMessage).where(ChatMessage.conversation_id == cid).order_by(ChatMessage.id.desc()).limit(6)).scalars()][::-1]
    db.add(ChatMessage(conversation_id=cid, role="user", content=body.message, meta={}, created_at=clock.now()))
    db.commit()
    res = chat.ask(db, body.message, hist)
    db.add(ChatMessage(conversation_id=cid, role="assistant", content=res.get("answer") or f"[{res['status']}]",
                       meta={k: v for k, v in res.items() if k != "answer"}, ai_run_id=res.get("ai_run_id"), created_at=clock.now()))
    db.commit()
    return {"conversation_id": cid, **res}


@router.get("/{conversation_id}")
def history(conversation_id: str, db: Session = Depends(get_db)) -> list[dict]:
    return [{"role": m.role, "content": m.content, "meta": m.meta, "at": iso(m.created_at)} for m in db.execute(
        select(ChatMessage).where(ChatMessage.conversation_id == conversation_id).order_by(ChatMessage.id)).scalars()]
