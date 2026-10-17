"""Shared API helpers."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import HTTPException, Query
from sqlalchemy.orm import Session

from .. import clock, kv
from ..services import metrics
from ..timeutil import local_date


def scope_params(
    days: int = Query(30, ge=1, le=366),
    start: date | None = None,
    end: date | None = None,
    group_id: int | None = None,
    include_staff: bool = False,
    include_bot: bool = False,
    datasets: str | None = Query(None, description="Comma-separated dataset labels, e.g. synthetic or import:3"),
) -> dict:
    return {"days": days, "start": start, "end": end, "group_id": group_id, "include_staff": include_staff,
            "include_bot": include_bot, "datasets": datasets}


def build_scope(session: Session, p: dict) -> metrics.Scope:
    try:
        gid = p["group_id"] or metrics.main_group_id(session)
    except LookupError as e:
        raise HTTPException(409, "No community data yet. Run the evaluation seed or sync first.") from e
    end = p["end"] or local_date(clock.now())
    start = p["start"] or (end - timedelta(days=p["days"] - 1))
    if start > end:
        raise HTTPException(400, "start must be on or before end")
    if (end - start).days > 400:
        raise HTTPException(400, "date range too large (max 400 days)")
    ds = [d.strip() for d in p["datasets"].split(",")] if p["datasets"] else (kv.get(session, "dataset_selection") or ["synthetic"])
    for d in ds:
        if d != "synthetic" and not d.startswith("import:"):
            raise HTTPException(400, f"unknown dataset label {d!r}")
    return metrics.Scope(group_id=gid, start=start, end=end, datasets=ds, include_staff=p["include_staff"],
                         include_bot=p["include_bot"])
