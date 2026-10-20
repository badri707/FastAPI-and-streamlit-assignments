from __future__ import annotations

import pytest
from sqlalchemy import select

from app import fixtures as fx
from app import models as m
from app.bootstrap import init_db
from app.config import Mode, Settings
from app.connectors.importer import ingest_bundle
from app.db import get_engine, reset_engines, session_scope


@pytest.fixture
def settings(tmp_path):
    reset_engines()
    st = Settings(data_dir=tmp_path)
    init_db(Mode.TEST, st)
    yield st
    reset_engines()


@pytest.fixture
def engine(settings):
    return get_engine(Mode.TEST, settings)


def ingest_steps(engine, steps):
    runs = []
    for when, bundle in steps:
        with session_scope(engine) as s:
            runs.append(ingest_bundle(s, fx.clone(bundle), Mode.TEST, when))
    return runs


@pytest.fixture
def seeded(engine):
    ingest_steps(engine, fx.initial_steps())
    return engine


def community(s):
    return s.scalar(select(m.Community).where(m.Community.slug == fx.SLUG))
