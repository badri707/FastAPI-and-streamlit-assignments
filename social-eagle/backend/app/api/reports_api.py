from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..security import require_admin
from ..services import metrics, reports
from ..timeutil import local_date
from .deps import build_scope, scope_params

router = APIRouter(prefix="/api", tags=["reports"], dependencies=[Depends(require_admin)])


@router.get("/overview")
def overview(sp: dict = Depends(scope_params), db: Session = Depends(get_db)) -> dict:
    return metrics.overview(db, build_scope(db, sp))


@router.get("/metrics/definitions")
def definitions() -> dict:
    return {"definitions": metrics.DEFINITIONS, "session_idle_cap_minutes": metrics.SESSION_IDLE_CAP_MIN}


@router.get("/reports/summary")
def summary(period: str = Query("daily", pattern="^(daily|weekly)$"), day: date | None = None, db: Session = Depends(get_db)) -> dict:
    d = day or (local_date(clock.now()) - timedelta(days=1))
    if period == "daily":
        return reports.daily_summary(db, d)
    gid = metrics.main_group_id(db)
    a = metrics.Scope(group_id=gid, start=d - timedelta(days=13), end=d - timedelta(days=7))
    b = metrics.Scope(group_id=gid, start=d - timedelta(days=6), end=d)
    return {"period": "weekly", "week": b.describe(), "comparison": metrics.compare(db, a, b),
            "support": metrics.support_metrics(db, b), "learning": metrics.learning(db, b)["progress_events_in_range"],
            "coverage": metrics.coverage(db, b)}


@router.get("/reports/support")
def support_report(sp: dict = Depends(scope_params), db: Session = Depends(get_db)) -> dict:
    scope = build_scope(db, sp)
    return {"scope": scope.describe(), **metrics.support_metrics(db, scope), "coverage": metrics.coverage(db, scope)}


@router.get("/reports/compare")
def compare(a_start: date, a_end: date, b_start: date, b_end: date, db: Session = Depends(get_db)) -> dict:
    gid = metrics.main_group_id(db)
    if a_start > a_end or b_start > b_end:
        raise HTTPException(400, "invalid range")
    return metrics.compare(db, metrics.Scope(gid, a_start, a_end), metrics.Scope(gid, b_start, b_end))


@router.get("/reports/export/{kind}")
def export(kind: str, sp: dict = Depends(scope_params), db: Session = Depends(get_db)) -> Response:
    if kind not in ("members", "daily", "support", "actions", "progress"):
        raise HTTPException(404, "unknown export")
    name, body = reports.export(db, kind, build_scope(db, sp))
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
