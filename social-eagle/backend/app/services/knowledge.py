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
import math
import re
from array import array
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import clock
from ..models import Course, KnowledgeChunk, KnowledgeDoc, KnowledgeEmbedding

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
        if not para or para.startswith("> SYNTHETIC"):  # provenance labels are not retrievable content
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
    return [(h, t) for h, t in chunks if t]


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

RRF_K = 60  # reciprocal-rank-fusion constant


def _vec_bytes(v: list[float]) -> bytes:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return array("f", [x / n for x in v]).tobytes()  # stored L2-normalised: cosine = dot product


def embed_pending(session: Session, batch: int = 16) -> dict[str, Any]:
    """Embed approved chunks that have no vector for the configured embedding model. Safe to call repeatedly;
    if the embedding model is unavailable nothing changes and retrieval stays keyword-only."""
    from ..ai.provider import AIUnavailable, get_provider
    from ..config import get_settings

    model = get_settings().ollama_embed_model
    done = select(KnowledgeEmbedding.chunk_id).where(KnowledgeEmbedding.model == model)
    rows = session.execute(select(KnowledgeChunk.id, KnowledgeChunk.heading, KnowledgeChunk.text)
                           .join(KnowledgeDoc, KnowledgeDoc.id == KnowledgeChunk.doc_id)
                           .where(KnowledgeDoc.status == "approved", KnowledgeChunk.id.not_in(done))).all()
    n = 0
    try:
        for i in range(0, len(rows), batch):
            part = rows[i:i + batch]
            used, vecs = get_provider().embed([f"search_document: {r.heading or ''}\n{r.text}" for r in part])
            for r, v in zip(part, vecs, strict=True):
                session.add(KnowledgeEmbedding(chunk_id=r.id, model=used, dim=len(v), vector=_vec_bytes(v), created_at=clock.now()))
                n += 1
            session.flush()
    except (AIUnavailable, AttributeError) as e:
        return {"embedded": n, "pending": len(rows) - n, "status": "unavailable", "detail": str(e)}
    return {"embedded": n, "pending": len(rows) - n, "status": "ok", "model": model}


@lru_cache(maxsize=512)
def _query_vec(model: str, question: str) -> tuple[float, ...] | None:
    from ..ai.provider import AIUnavailable, get_provider

    try:
        _m, vecs = get_provider().embed([f"search_query: {question}"])
    except (AIUnavailable, AttributeError):
        return None
    v = vecs[0]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return tuple(x / n for x in v)


def _semantic_ranks(session: Session, question: str, limit: int = 30) -> dict[int, tuple[int, float]]:
    """chunk_id -> (rank, cosine) for the top `limit` approved chunks by embedding similarity; empty if unavailable."""
    from ..config import get_settings

    model = get_settings().ollama_embed_model
    rows = session.execute(select(KnowledgeEmbedding.chunk_id, KnowledgeEmbedding.vector)
                           .join(KnowledgeChunk, KnowledgeChunk.id == KnowledgeEmbedding.chunk_id)
                           .join(KnowledgeDoc, KnowledgeDoc.id == KnowledgeChunk.doc_id)
                           .where(KnowledgeEmbedding.model == model, KnowledgeDoc.status == "approved")).all()
    if not rows:
        return {}
    q = _query_vec(model, question)
    if q is None:
        return {}
    scored = []
    for cid, blob in rows:
        v = array("f")
        v.frombytes(blob)
        if len(v) == len(q):
            scored.append((sum(a * b for a, b in zip(q, v, strict=True)), cid))
    scored.sort(reverse=True)
    return {cid: (rank, cos) for rank, (cos, cid) in enumerate(scored[:limit], start=1)}


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
    cosine: float | None = None

    def ref(self) -> dict[str, Any]:
        return {"chunk_id": self.chunk_id, "doc_id": self.doc_id, "doc_key": self.doc_key,
                "version": self.doc_version, "score": round(self.score, 3),
                "cosine": None if self.cosine is None else round(self.cosine, 3)}


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
    """Hybrid retrieval: FTS5 BM25 ranks fused with embedding-similarity ranks (reciprocal rank fusion). Falls back
    to keyword-only when no embeddings are available. Returns (permitted passages, restricted matches as metadata)."""
    q = fts_query(question)
    lexical: list[int] = []
    if q is not None:
        lexical = [r[0] for r in session.execute(
            text("SELECT c.id FROM knowledge_fts JOIN knowledge_chunks c ON c.id = knowledge_fts.rowid "
                 "JOIN knowledge_docs d ON d.id = c.doc_id WHERE knowledge_fts MATCH :q AND d.status = 'approved' "
                 "ORDER BY bm25(knowledge_fts, 2.0, 1.0) LIMIT 30"), {"q": q}).fetchall()]
    semantic = _semantic_ranks(session, question) if (q is not None or question.strip()) else {}
    if not lexical and not semantic:
        return [], []
    fused: dict[int, float] = {}
    for rank, cid in enumerate(lexical, start=1):
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank)
    for cid, (rank, _cos) in semantic.items():
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank)
    order = sorted(fused, key=lambda c: -fused[c])
    rows = {r.id: r for r in session.execute(
        select(KnowledgeChunk.id, KnowledgeChunk.doc_id, KnowledgeChunk.heading, KnowledgeChunk.text, KnowledgeDoc.doc_key,
               KnowledgeDoc.version, KnowledgeDoc.title, KnowledgeDoc.access_tiers, KnowledgeDoc.course_upstream_id,
               KnowledgeDoc.lesson_upstream_id, KnowledgeDoc.updated_label)
        .join(KnowledgeDoc, KnowledgeDoc.id == KnowledgeChunk.doc_id).where(KnowledgeChunk.id.in_(order))).all()}
    mode = "hybrid" if semantic else "lexical"
    permitted: list[Passage] = []
    restricted: dict[str, dict[str, Any]] = {}
    used = 0
    for cid in order:
        r = rows[cid]
        score = round(fused[cid] * 1000, 3)
        cos = semantic[cid][1] if cid in semantic else None
        if not (owner or tier_allows(r.access_tiers, tier, extra_tiers)):
            if r.course_upstream_id and r.course_upstream_id not in restricted:
                course = session.execute(select(Course).filter_by(upstream_id=r.course_upstream_id)).scalars().first()
                restricted[r.course_upstream_id] = {"course_upstream_id": r.course_upstream_id,
                                                    "course_title": course.title if course else r.course_upstream_id,
                                                    "required_tiers": r.access_tiers, "score": score, "cosine": cos, "mode": mode}
            continue
        if len(permitted) >= k or used + len(r.text) > max_chars:
            continue
        permitted.append(Passage(r.id, r.doc_id, r.doc_key, r.version, r.title, r.heading, r.text, score,
                                 r.course_upstream_id, r.lesson_upstream_id, r.updated_label, cos))
        used += len(r.text)
    return permitted, list(restricted.values())
