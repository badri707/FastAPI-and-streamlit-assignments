"""Permission-scoped lesson search (SQLite FTS5).

A member only retrieves passages from courses they are entitled to at the time
of the query. This is deterministic retrieval only; no AI is involved here.
"""
from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models as m
from app.timeutil import sql_ts


def rebuild_index(s: Session) -> int:
    s.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS lesson_fts USING fts5(title, body, lesson_id UNINDEXED, "
                   "course_id UNINDEXED)"))
    s.execute(text("DELETE FROM lesson_fts"))
    rows = s.query(m.Lesson).all()
    for lsn in rows:
        s.execute(text("INSERT INTO lesson_fts(title, body, lesson_id, course_id) VALUES (:t, :b, :l, :c)"),
                  {"t": lsn.title, "b": lsn.body or "", "l": lsn.id, "c": lsn.course_id})
    return len(rows)


def _fts_query(q: str) -> str:
    terms = re.findall(r"[A-Za-z0-9]+", q)
    return " OR ".join(f'"{t}"' for t in terms[:12]) or '""'


def search_lessons(s: Session, query: str, member_id: int | None, at: datetime, limit: int = 5) -> list[dict]:
    """member_id=None means admin scope (all courses)."""
    allowed_sql = ""
    params: dict = {"q": _fts_query(query), "lim": limit, "at": sql_ts(at)}
    if member_id is not None:
        allowed_sql = ("AND CAST(f.course_id AS INTEGER) IN (SELECT course_id FROM entitlements WHERE member_id = :mid "
                       "AND valid_from <= :at AND (valid_to IS NULL OR valid_to > :at))")
        params["mid"] = member_id
    rows = s.execute(text(
        "SELECT f.lesson_id, f.title, snippet(lesson_fts, 1, '[', ']', '…', 12) AS snip, c.title AS course, c.id AS cid "
        "FROM lesson_fts f JOIN courses c ON c.id = CAST(f.course_id AS INTEGER) "
        f"WHERE lesson_fts MATCH :q {allowed_sql} ORDER BY rank LIMIT :lim"), params).all()
    return [{"lesson_id": int(r.lesson_id), "lesson_title": r.title, "course": r.course, "course_id": r.cid,
             "snippet": r.snip, "link": f"/lessons/{int(r.lesson_id)}"} for r in rows]
