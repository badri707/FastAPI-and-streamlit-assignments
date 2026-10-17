"""Programmatic Alembic upgrade used by setup scripts, tests and reset-evaluation."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[1]


def upgrade(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


if __name__ == "__main__":
    from .config import get_settings

    upgrade(get_settings().app_db_path)
    print(f"migrated {get_settings().app_db_path}")
