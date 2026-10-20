"""Database initialisation via Alembic migrations (per mode)."""
from __future__ import annotations

from alembic import command
from alembic.config import Config

from app.config import PROJECT_ROOT, Mode, Settings, get_settings
from app.db import get_engine


def alembic_config(url: str) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def init_db(mode: Mode, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    eng = get_engine(mode, settings)
    with eng.begin() as conn:
        cfg = alembic_config(str(eng.url))
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
