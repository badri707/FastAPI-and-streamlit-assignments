"""Optional CSV/JSON import with mapping preview, schema checks and provenance.

Imported rows go into a separate group ("Imported: <file>") with dataset "import:<batch id>", so they are never
mixed with synthetic statistics unless explicitly selected. Re-importing an identical file is detected by SHA-256.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..models import Group, ImportBatch, Member, Post
from ..timeutil import parse_ts

SCHEMAS: dict[str, dict[str, dict[str, Any]]] = {
    "members": {
        "upstream_id": {"required": True, "aliases": ["id", "member_id", "user_id"]},
        "display_name": {"required": True, "aliases": ["name", "full_name"]},
        "email": {"required": False, "aliases": ["email_address", "mail"]},
        "joined_at": {"required": False, "aliases": ["join_date", "joined", "created_at"], "type": "datetime"},
        "tier": {"required": False, "aliases": ["plan", "membership", "level"]},
        "role": {"required": False, "aliases": []},
    },
    "posts": {
        "upstream_id": {"required": True, "aliases": ["id", "post_id"]},
        "author_upstream_id": {"required": True, "aliases": ["author_id", "member_id", "user_id"]},
        "title": {"required": False, "aliases": ["subject"]},
        "body": {"required": True, "aliases": ["content", "text", "message"]},
        "created_at": {"required": True, "aliases": ["date", "timestamp", "posted_at"], "type": "datetime"},
        "category": {"required": False, "aliases": []},
    },
}
MAX_BYTES = 10_000_000
MAX_ROWS = 50_000


class ImportError_(ValueError):
    pass


def _rows(filename: str, data: bytes) -> tuple[str, list[dict[str, Any]]]:
    if len(data) > MAX_BYTES:
        raise ImportError_("File too large (max 10 MB)")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ImportError_("File must be UTF-8") from e
    if filename.lower().endswith(".json"):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            raise ImportError_(f"Invalid JSON: {e}") from e
        rows = obj if isinstance(obj, list) else obj.get("rows") if isinstance(obj, dict) else None
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise ImportError_("JSON must be a list of objects (or {\"rows\": [...]})")
        fmt = "json"
    elif filename.lower().endswith(".csv"):
        rows = list(csv.DictReader(io.StringIO(text)))
        fmt = "csv"
    else:
        raise ImportError_("Only .csv and .json files are accepted")
    if len(rows) > MAX_ROWS:
        raise ImportError_(f"Too many rows (max {MAX_ROWS})")
    return fmt, rows


def suggest_mapping(entity: str, columns: list[str]) -> dict[str, str | None]:
    schema = SCHEMAS[entity]
    norm = {re.sub(r"[^a-z0-9]", "_", c.lower()).strip("_"): c for c in columns}
    out: dict[str, str | None] = {}
    for field, spec in schema.items():
        out[field] = next((norm[n] for n in [field, *spec["aliases"]] if n in norm), None)
    return out


def _validate(entity: str, rows: list[dict[str, Any]], mapping: dict[str, str | None]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    schema = SCHEMAS[entity]
    missing = [f for f, spec in schema.items() if spec["required"] and not mapping.get(f)]
    if missing:
        raise ImportError_(f"Required fields are not mapped: {', '.join(missing)}")
    ok, errors = [], []
    seen: set[str] = set()
    for i, r in enumerate(rows, start=1):
        rec: dict[str, Any] = {}
        errs = []
        for f, spec in schema.items():
            col = mapping.get(f)
            v = r.get(col) if col else None
            v = v.strip() if isinstance(v, str) else v
            if spec["required"] and not v:
                errs.append(f"{f} is empty")
                continue
            if v and spec.get("type") == "datetime":
                try:
                    v = parse_ts(str(v))
                except ValueError:
                    errs.append(f"{f} is not an ISO date/time: {str(v)[:30]}")
                    continue
            rec[f] = v or None
        if rec.get("upstream_id") in seen:
            errs.append("duplicate upstream_id in file")
        if errs:
            errors.append({"row": i, "errors": errs})
        else:
            seen.add(rec["upstream_id"])
            ok.append(rec)
    return ok, errors


def preview(session: Session, *, filename: str, data: bytes, entity: str, mapping: dict[str, str | None] | None) -> dict[str, Any]:
    if entity not in SCHEMAS:
        raise ImportError_(f"Unknown entity {entity}")
    fmt, rows = _rows(filename, data)
    cols = list(rows[0].keys()) if rows else []
    mapping = mapping or suggest_mapping(entity, cols)
    sha = hashlib.sha256(data).hexdigest()
    dup = session.execute(select(ImportBatch).where(ImportBatch.sha256 == sha, ImportBatch.entity == entity,
                                                    ImportBatch.status == "committed")).scalars().first()
    ok, errors = _validate(entity, rows, mapping) if rows else ([], [])
    batch = ImportBatch(filename=filename[:300], entity=entity, fmt=fmt, sha256=sha, status="previewed", mapping=mapping,
                        rows_total=len(rows), rows_ok=len(ok), rows_rejected=len(errors), errors=errors[:200],
                        provenance_note=f"User-supplied file {filename} ({fmt}); not verified against any live source.",
                        created_at=clock.now())
    session.add(batch)
    session.commit()
    return {"batch_id": batch.id, "format": fmt, "columns": cols, "mapping": mapping, "schema": SCHEMAS[entity],
            "rows_total": len(rows), "rows_ok": len(ok), "rows_rejected": len(errors), "errors": errors[:50],
            "sample": [{k: str(v) for k, v in r.items()} for r in ok[:5]],
            "duplicate_of_batch": dup.id if dup else None, "provenance_note": batch.provenance_note}


def commit(session: Session, batch_id: int, data: bytes, mapping: dict[str, str | None] | None = None) -> dict[str, Any]:
    batch = session.get(ImportBatch, batch_id)
    if batch is None or batch.status != "previewed":
        raise ImportError_("Batch not found or already processed")
    if hashlib.sha256(data).hexdigest() != batch.sha256:
        raise ImportError_("File changed since preview; preview again")
    dup = session.execute(select(ImportBatch).where(ImportBatch.sha256 == batch.sha256, ImportBatch.entity == batch.entity,
                                                    ImportBatch.status == "committed")).scalars().first()
    if dup:
        batch.status = "rejected"
        session.commit()
        raise ImportError_(f"Identical file already imported as batch {dup.id}; nothing changed")
    _fmt, rows = _rows(batch.filename, data)
    mapping = mapping or batch.mapping
    ok, errors = _validate(batch.entity, rows, mapping)
    dataset = f"import:{batch.id}"
    group = Group(upstream_id=f"import-{batch.id}", name=f"Imported: {batch.filename}", source="import", dataset=dataset,
                  created_at=clock.now())
    session.add(group)
    session.flush()
    now = clock.now()
    inserted = 0
    if batch.entity == "members":
        for r in ok:
            session.add(Member(group_id=group.id, upstream_id=str(r["upstream_id"]), display_name=r["display_name"],
                               email=r.get("email"), role=r.get("role") or "member", tier=r.get("tier"),
                               joined_at=r.get("joined_at"), status="active", dataset=dataset, first_observed_at=now,
                               observed_at=now))
            inserted += 1
    else:
        members = {m.upstream_id: m.id for m in session.execute(select(Member).where(Member.group_id == group.id)).scalars()}
        for r in ok:
            mid = members.get(str(r["author_upstream_id"]))
            if mid is None:
                m = Member(group_id=group.id, upstream_id=str(r["author_upstream_id"]),
                           display_name=f"Imported author {r['author_upstream_id']}", status="active", dataset=dataset,
                           first_observed_at=now, observed_at=now)
                session.add(m)
                session.flush()
                mid = members[m.upstream_id] = m.id
            session.add(Post(group_id=group.id, upstream_id=str(r["upstream_id"]), author_id=mid, kind="post",
                             title=r.get("title"), body=r["body"], category=r.get("category"), created_at=r["created_at"],
                             observed_at=now, dataset=dataset))
            inserted += 1
    batch.status, batch.group_id, batch.rows_ok, batch.rows_rejected = "committed", group.id, inserted, len(errors)
    batch.errors = errors[:200]
    session.commit()
    return {"batch_id": batch.id, "group_id": group.id, "dataset": dataset, "inserted": inserted, "rejected": len(errors)}


def delete_batch(session: Session, batch_id: int) -> dict[str, Any]:
    batch = session.get(ImportBatch, batch_id)
    if batch is None or batch.status != "committed" or batch.group_id is None:
        raise ImportError_("Only committed batches can be deleted")
    g = session.get(Group, batch.group_id)
    if g is not None:
        session.delete(g)  # cascades to members/posts in that group
    batch.status = "deleted"
    session.commit()
    return {"deleted_batch": batch_id}
