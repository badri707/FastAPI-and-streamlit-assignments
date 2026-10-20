"""Per-mode SQLite engines. Each mode has its own database file so synthetic,
public and (future) private data can never be mixed in one query."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Mode, Settings, get_settings

_engines: dict[str, Engine] = {}


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


def make_engine(path: Path | str) -> Engine:
    url = "sqlite://" if str(path) == ":memory:" else f"sqlite:///{path}"
    eng = create_engine(url, pool_size=5, max_overflow=0, pool_timeout=10) if url != "sqlite://" else create_engine(url)
    event.listen(eng, "connect", _sqlite_pragmas)
    return eng


def get_engine(mode: Mode, settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    path = settings.db_path(mode)  # raises for private mode
    key = str(path)
    if key not in _engines:
        path.parent.mkdir(parents=True, exist_ok=True)
        _engines[key] = make_engine(path)
    return _engines[key]


def reset_engines() -> None:
    for eng in _engines.values():
        eng.dispose()
    _engines.clear()


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Short transaction: commit on success, roll back on error."""
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
