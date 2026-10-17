from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import KnowledgeChunk, KnowledgeDoc
from ..security import require_admin
from ..services import knowledge, notify
from ..timeutil import iso

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"], dependencies=[Depends(require_admin)])


def _doc(d: KnowledgeDoc, chunks: int | None = None) -> dict:
    return {"id": d.id, "doc_key": d.doc_key, "title": d.title, "kind": d.kind, "source_path": d.source_path,
            "course": d.course_upstream_id, "lesson": d.lesson_upstream_id, "access_tiers": d.access_tiers, "version": d.version,
            "status": d.status, "status_detail": d.status_detail, "updated_label": d.updated_label, "dataset": d.dataset,
            "sha256": d.sha256[:16], "created_at": iso(d.created_at), "chunks": chunks}


@router.get("/docs")
def docs(db: Session = Depends(get_db)) -> list[dict]:
    out = []
    for d in db.execute(select(KnowledgeDoc).order_by(KnowledgeDoc.doc_key, KnowledgeDoc.version.desc())).scalars():
        n = len(db.execute(select(KnowledgeChunk.id).where(KnowledgeChunk.doc_id == d.id)).all())
        out.append(_doc(d, n))
    return out


@router.get("/docs/{doc_id}")
def doc(doc_id: int, db: Session = Depends(get_db)) -> dict:
    d = db.get(KnowledgeDoc, doc_id)
    if d is None:
        raise HTTPException(404, "document not found")
    chunks = db.execute(select(KnowledgeChunk).where(KnowledgeChunk.doc_id == d.id).order_by(KnowledgeChunk.ordinal)).scalars().all()
    versions = db.execute(select(KnowledgeDoc).where(KnowledgeDoc.doc_key == d.doc_key).order_by(KnowledgeDoc.version.desc())).scalars().all()
    return {**_doc(d, len(chunks)), "chunk_list": [{"id": c.id, "ordinal": c.ordinal, "heading": c.heading, "text": c.text} for c in chunks],
            "versions": [{"id": v.id, "version": v.version, "status": v.status, "created_at": iso(v.created_at)} for v in versions]}


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    access_tiers: str = Form("*", max_length=200, pattern=r"^(\*|[a-z0-9_-]+(,[a-z0-9_-]+)*)$"),
    title: str | None = Form(None, max_length=300),
    course: str | None = Form(None, max_length=120, pattern=r"^[A-Za-z0-9_-]+$"),
    db: Session = Depends(get_db),
    user=Depends(require_admin),  # type: ignore[no-untyped-def]
) -> dict:
    data = await file.read(knowledge.MAX_BYTES + 1)
    name = (file.filename or "upload").replace("\\", "/").split("/")[-1][:200]
    meta = {"access_tiers": access_tiers}
    if title:
        meta["title"] = title
    if course:
        meta["course"] = course
    try:
        res = knowledge.ingest_bytes(db, filename=name, data=data, meta_override=meta, dataset="upload",
                                     source_path=f"upload:{name}")
    except knowledge.IngestError as e:
        raise HTTPException(400, str(e)) from e
    emb = knowledge.embed_pending(db)
    notify.audit(db, user.username, "knowledge.upload", doc_key=res.doc_key, version=res.version, status=res.status)
    db.commit()
    return {**res.__dict__, "embeddings": emb}


class StatusIn(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")


@router.post("/docs/{doc_id}/status")
def set_status(doc_id: int, body: StatusIn, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    d = db.get(KnowledgeDoc, doc_id)
    if d is None:
        raise HTTPException(404, "document not found")
    if d.status == "needs_ocr" and body.status == "approved":
        raise HTTPException(400, "A scanned PDF without extracted text cannot be approved; OCR is required first")
    d.status = body.status
    notify.audit(db, user.username, "knowledge.status", doc_id=doc_id, status=body.status)
    db.commit()
    return _doc(d)


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    tier: str | None = Field(None, max_length=40)
    owner: bool = False


@router.post("/search")
def search(body: SearchIn, db: Session = Depends(get_db)) -> dict:
    passages, restricted = knowledge.retrieve(db, body.query, tier=body.tier, owner=body.owner, k=8, max_chars=6000)
    return {"passages": [{**p.ref(), "title": p.title, "heading": p.heading, "text": p.text, "link": f"/knowledge/{p.doc_id}#chunk-{p.chunk_id}",
                          "updated": p.updated_label} for p in passages],
            "restricted_matches": restricted,
            "note": "Restricted matches are listed by course only; their content is not shown for this tier."}
