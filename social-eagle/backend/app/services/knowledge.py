"""Knowledge ingestion and permission-aware retrieval.

- Accepts Markdown, text, transcripts and text-based PDFs. Scanned (image-only) PDFs are detected and
  marked `needs_ocr` with an explanation; no text is invented for them.
- Each file has a stable `doc_key`; a changed file creates a new version and supersedes the old one.
- Retrieval uses SQLite FTS5 (BM25) and filters by the asking member's tier. Restricted matches are
  reported only as metadata (course title), never as content.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import clock
from ..models import Course, KnowledgeChunk, KnowledgeDoc

ALLOWED_EXT = {".md": "markdown", ".markdown": "markdown", ".txt": "text", ".pdf": "pdf"}
MAX_BYTES = 5_000_000
CHUNK_CHARS = 700
STOPWORDS = set(["a", "an", "the", "and", "or", "but", "if", "then", "so", "to", "of", "in", "on", "for", "with", "at", "by", "from", "is", "are", "was", "were", "be", "been", "being", "do", "does", "did", "i", "me", "my", "we", "our", "you", "your", "he", "she", "it", "its", "they", "them", "this", "that", "these", "those", "what", "which", "who", "whom", "how", "why", "when", "where", "can", "could", "should", "would", "will", "shall", "may", "might", "must", "have", "has", "had", "not", "no", "yes", "any", "some", "all", "just", "about", "into", "over", "than", "too", "very", "please", "there", "here", "also", "get", "got", "want", "need", "know", "like", "really", "much", "many", "more", "most", "other", "such", "only", "own", "same"])


class IngestError(ValueError):
    pass


def _front_matter(raw: str) -> tuple[dict[str, str], str]:
    if raw.startswith("---\n"):
        end = raw.find("\n---", 4)
        if end != -1:
            meta = {}
            for line in raw[4:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            return meta, raw[end + 4 :].lstrip("\n")
    return {}, raw


def extract_pdf_text(data: bytes) -> tuple[str, int]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [(p.extract_text() or "").strip() for p in reader.pages]
    return "\n\n".join(pages), len(pages)


def chunk_text(body: str) -> list[tuple[str | None, str]]:
    """Split on Markdown headings, then pack paragraphs into ~CHUNK_CHARS chunks."""
    chunks: list[tuple[str | None, str]] = []
    heading: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if buf:
            chunks.append((heading, "\n\n".join(buf).strip()))
            buf.clear()

    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para:
            continue
        if para.startswith("#"):
            flush()
            heading = para.lstrip("#").strip().split("\n")[0]
            rest = para.split("\n", 1)[1].strip() if "\n" in para else ""
            if rest:
                buf.append(rest)
            continue
        if sum(len(b) for b in buf) + len(para) > CHUNK_CHARS:
            flush()
        buf.append(para)
    flush()
    return [(h, t) for h, t in chunks if t and not t.startswith("> SYNTHETIC")] or chunks


@dataclass
class IngestResult:
    doc_id: int
    doc_key: str
    version: int
    status: str
    chunks: int
    detail: str | None = None
    unchanged: bool = False


def ingest_bytes(
    session: Session,
    *,
    filename: str,
    data: bytes,
    meta_override: dict[str, str] | None = None,
    dataset: str = "synthetic",
    source_path: str | None = None,
) -> IngestResult:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise IngestError(f"Unsupported file type {ext!r}; allowed: {', '.join(sorted(ALLOWED_EXT))}")
    if len(data) > MAX_BYTES:
        raise IngestError("File too large (max 5 MB)")
    sha = hashlib.sha256(data).hexdigest()
    meta: dict[str, str] = {}
    status, detail = "approved", None
    if ext == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise IngestError("File does not look like a PDF")
        try:
            body, n_pages = extract_pdf_text(data)
        except Exception as e:  # malformed PDF
            raise IngestError(f"Could not parse PDF: {e}") from e
        if len(body.strip()) < 40 * max(n_pages, 1) // 2:
            status = "needs_ocr"
            detail = (f"No extractable text found in {n_pages} page(s). This looks like a scanned/image-only PDF. "
                      "OCR is required before it can be used as knowledge; no OCR is performed in this build.")
            body = ""
        kind = "pdf"
    else:
        try:
            raw = data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise IngestError("Text files must be UTF-8") from e
        meta, body = _front_matter(raw)
        kind = meta.get("kind") or ALLOWED_EXT[ext]
    meta.update(meta_override or {})
    doc_key = meta.get("doc_key") or f"file:{Path(filename).stem}"
    title = meta.get("title") or Path(filename).stem
    latest = session.execute(
        select(KnowledgeDoc).where(KnowledgeDoc.doc_key == doc_key).order_by(KnowledgeDoc.version.desc())
    ).scalars().first()
    if latest is not None and latest.sha256 == sha:
        return IngestResult(latest.id, doc_key, latest.version, latest.status, 0, latest.status_detail, unchanged=True)
    version = (latest.version + 1) if latest else int(meta.get("version", "1") or 1)
    if latest is not None and latest.status == "approved":
        latest.status = "superseded"
        latest.status_detail = f"Superseded by version {version}"
    doc = KnowledgeDoc(
        doc_key=doc_key, title=title, kind=kind, source_path=source_path or filename,
        course_upstream_id=meta.get("course"), lesson_upstream_id=meta.get("lesson"),
        access_tiers=meta.get("access_tiers", "*") or "*", version=version, sha256=sha, status=status,
        status_detail=detail, updated_label=meta.get("updated_label"), dataset=dataset, created_at=clock.now(),
    )
    session.add(doc)
    session.flush()
    n = 0
    if status == "approved":
        for i, (heading, chunk) in enumerate(chunk_text(body)):
            session.add(KnowledgeChunk(doc_id=doc.id, ordinal=i, heading=heading or title, text=chunk))
            n += 1
        session.flush()
    return IngestResult(doc.id, doc_key, version, status, n, detail)


def ingest_directory(session: Session, directory: Path, dataset: str = "synthetic") -> list[IngestResult]:
    manifest_path = directory.parent / "knowledge.manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    out = []
    for f in sorted(directory.iterdir()):
        if f.suffix.lower() in ALLOWED_EXT:
            out.append(ingest_bytes(session, filename=f.name, data=f.read_bytes(), meta_override=manifest.get(f.name),
                                    dataset=dataset, source_path=f"seed/knowledge/{f.name}"))
    return out


# ---------------------------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------------------------

@dataclass
class Passage:
    chunk_id: int
    doc_id: int
    doc_key: str
    doc_version: int
    title: str
    heading: str | None
    text: str
    score: float
    course_upstream_id: str | None
    lesson_upstream_id: str | None
    updated_label: str | None

    def ref(self) -> dict[str, Any]:
        return {"chunk_id": self.chunk_id, "doc_id": self.doc_id, "doc_key": self.doc_key,
                "version": self.doc_version, "score": round(self.score, 3)}


def fts_query(question: str) -> str | None:
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", question)]
    terms = [w for w in words if len(w) > 1 and w not in STOPWORDS]
    if not terms:
        return None
    # Quote each term so FTS5 operators in user text are inert.
    return " OR ".join(f'"{t}"' for t in dict.fromkeys(terms))


def tier_allows(access_tiers: str, tier: str | None, extra_tiers: list[str] | None = None) -> bool:
    allowed = [t.strip() for t in access_tiers.split(",")]
    if "*" in allowed:
        return True
    mine = {t for t in [tier, *(extra_tiers or [])] if t}
    return bool(mine & set(allowed))


def retrieve(
    session: Session,
    question: str,
    *,
    tier: str | None,
    extra_tiers: list[str] | None = None,
    owner: bool = False,
    k: int = 5,
    max_chars: int = 2600,
) -> tuple[list[Passage], list[dict[str, Any]]]:
    """Returns (permitted passages, restricted matches as metadata only)."""
    q = fts_query(question)
    if q is None:
        return [], []
    rows = session.execute(
        text(
            "SELECT c.id, c.doc_id, c.heading, c.text, bm25(knowledge_fts, 2.0, 1.0) AS score, d.doc_key, d.version, "
            "d.title, d.access_tiers, d.course_upstream_id, d.lesson_upstream_id, d.updated_label "
            "FROM knowledge_fts JOIN knowledge_chunks c ON c.id = knowledge_fts.rowid "
            "JOIN knowledge_docs d ON d.id = c.doc_id "
            "WHERE knowledge_fts MATCH :q AND d.status = 'approved' ORDER BY score LIMIT 40"
        ),
        {"q": q},
    ).fetchall()
    permitted: list[Passage] = []
    restricted: dict[str, dict[str, Any]] = {}
    used = 0
    for r in rows:
        allowed = owner or tier_allows(r.access_tiers, tier, extra_tiers)
        if not allowed:
            if r.course_upstream_id and r.course_upstream_id not in restricted:
                course = session.execute(select(Course).filter_by(upstream_id=r.course_upstream_id)).scalars().first()
                restricted[r.course_upstream_id] = {"course_upstream_id": r.course_upstream_id,
                                                    "course_title": course.title if course else r.course_upstream_id,
                                                    "required_tiers": r.access_tiers, "score": -float(r.score)}
            continue
        if len(permitted) >= k or used + len(r.text) > max_chars:
            continue
        permitted.append(Passage(r.id, r.doc_id, r.doc_key, r.version, r.title, r.heading, r.text, -float(r.score),
                                 r.course_upstream_id, r.lesson_upstream_id, r.updated_label))
        used += len(r.text)
    return permitted, list(restricted.values())
