from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from app import models  # noqa: F401  (register tables)
from app.config import get_settings
from app.db import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url and "driver://" not in url:
        return url
    return f"sqlite:///{get_settings().app_db_path}"


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is None:
        cfg = config.get_section(config.config_ini_section, {})
        cfg["sqlalchemy.url"] = _url()
        engine = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
            with context.begin_transaction():
                context.run_migrations()
            connection.commit()
    else:
        context.configure(connection=connectable, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
