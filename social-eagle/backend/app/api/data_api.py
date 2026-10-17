"""Imports, backups, per-member export/erasure and retention."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import ImportBatch, Member, MemberNote, MemberTag, Post
from ..security import require_admin
from ..services import backup, importer, notify, retention
from ..timeutil import iso

router = APIRouter(prefix="/api", tags=["data"], dependencies=[Depends(require_admin)])


def _import_store(batch_id: int) -> Path:
    d = get_settings().data_dir / "imports"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"batch-{batch_id}.bin"


@router.post("/import/preview")
async def import_preview(file: UploadFile = File(...), entity: str = Form(..., pattern="^(members|posts)$"),
                         mapping: str | None = Form(None, max_length=4000), db: Session = Depends(get_db)) -> dict:
    data = await file.read(importer.MAX_BYTES + 1)
    name = (file.filename or "upload").replace("\\", "/").split("/")[-1][:200]
    try:
        mp = json.loads(mapping) if mapping else None
        if mp is not None and not isinstance(mp, dict):
            raise HTTPException(400, "mapping must be a JSON object")
        res = importer.preview(db, filename=name, data=data, entity=entity, mapping=mp)
    except (importer.ImportError_, json.JSONDecodeError) as e:
        raise HTTPException(400, str(e)) from e
    _import_store(res["batch_id"]).write_bytes(data)
    return res


class CommitIn(BaseModel):
    mapping: dict[str, str | None] | None = None


@router.post("/import/{batch_id}/commit")
def import_commit(batch_id: int, body: CommitIn, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    p = _import_store(batch_id)
    if not p.exists():
        raise HTTPException(404, "preview file not found; preview again")
    try:
        res = importer.commit(db, batch_id, p.read_bytes(), body.mapping)
    except importer.ImportError_ as e:
        raise HTTPException(400, str(e)) from e
    p.unlink(missing_ok=True)
    notify.audit(db, user.username, "import.commit", **res)
    db.commit()
    return {**res, "note": "Imported rows are kept in their own group and dataset label; they are excluded from synthetic "
                           "statistics unless you explicitly select that dataset."}


@router.get("/import/batches")
def batches(db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": b.id, "filename": b.filename, "entity": b.entity, "status": b.status, "rows_total": b.rows_total,
             "rows_ok": b.rows_ok, "rows_rejected": b.rows_rejected, "dataset": f"import:{b.id}" if b.status == "committed" else None,
             "group_id": b.group_id, "provenance": b.provenance_note, "created_at": iso(b.created_at)}
            for b in db.execute(select(ImportBatch).order_by(ImportBatch.id.desc())).scalars()]


@router.delete("/import/{batch_id}")
def delete_batch(batch_id: int, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    try:
        res = importer.delete_batch(db, batch_id)
    except importer.ImportError_ as e:
        raise HTTPException(400, str(e)) from e
    notify.audit(db, user.username, "import.delete", batch_id=batch_id)
    db.commit()
    return res


@router.get("/backups")
def list_backups() -> dict:
    s = get_settings()
    return {"backups": backup.list_backups(), "directory": str(s.effective_backup_dir),
            "free_mb": round(backup.free_mb(s.effective_backup_dir))}


@router.post("/backups")
def make_backup(user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    try:
        return backup.create_backup(label="manual")
    except OSError as e:
        raise HTTPException(507, str(e)) from e


class VerifyIn(BaseModel):
    name: str = Field(pattern=r"^backup-[A-Za-z0-9_-]+$")


@router.post("/backups/verify")
def verify_backup(body: VerifyIn) -> dict:
    s = get_settings()
    src = s.effective_backup_dir / body.name
    if not (src / "manifest.json").exists():
        raise HTTPException(404, "backup not found")
    target = s.data_dir / "restore-check" / body.name
    return backup.verify_and_restore(src, target)


@router.get("/members/{member_id}/export")
def export_member(member_id: int, db: Session = Depends(get_db)) -> Response:
    m = db.get(Member, member_id)
    if m is None:
        raise HTTPException(404, "member not found")
    data = {"member": {c.name: str(getattr(m, c.name)) for c in Member.__table__.columns},
            "tags": [t.tag for t in m.tags],
            "notes": [{"body": n.body, "author": n.author, "at": iso(n.created_at)} for n in
                      db.execute(select(MemberNote).where(MemberNote.member_id == m.id)).scalars()],
            "posts": [{"upstream_id": p.upstream_id, "kind": p.kind, "title": p.title, "body": p.body, "at": iso(p.created_at)}
                      for p in db.execute(select(Post).where(Post.author_id == m.id)).scalars()],
            "note": "Data held locally by this application about this member."}
    return Response(json.dumps(data, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="member-{m.id}.json"'})


@router.post("/members/{member_id}/erase")
def erase_member(member_id: int, db: Session = Depends(get_db), user=Depends(require_admin)) -> dict:  # type: ignore[no-untyped-def]
    """Erase personal data held locally. The source community is not changed; future syncs keep the erasure."""
    m = db.get(Member, member_id)
    if m is None:
        raise HTTPException(404, "member not found")
    m.display_name, m.email = f"Erased member #{m.id}", None
    db.query(MemberNote).filter(MemberNote.member_id == m.id).delete()
    if "local:erased" not in {t.tag for t in m.tags}:
        m.tags.append(MemberTag(tag="local:erased"))
    for p in db.execute(select(Post).where(Post.author_id == m.id)).scalars():
        p.body, p.title = "[content erased locally]", None
    notify.audit(db, user.username, "member.erase", member_id=m.id)
    db.commit()
    return {"ok": True, "note": "Personal fields, notes and post text erased in this application. The (synthetic) source is unchanged."}


@router.post("/retention/run")
def run_retention(db: Session = Depends(get_db)) -> dict:
    return retention.apply(db)
