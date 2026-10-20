"""FastAPI app: dashboard pages + JSON API. Same origin, loopback only.

All numbers on monitoring pages come from ``build_report`` for the selected
date, so the dashboard and the issued reports share one set of metric
definitions.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import func, or_, select

from app import models as m
from app.bootstrap import init_db
from app.config import CALC_VERSION, Mode, PrivateModeDisabled, Settings, get_settings
from app.connectors.importer import ImportRejected, ingest_bundle
from app.db import get_engine, session_scope
from app.reports.daily import build_report, issue_report, render_csv, render_html
from app.reports.member_export import build_member_evidence, render_member_html
from app.retrieval import rebuild_index, search_lessons
from app.timeutil import Clock, fmt_local, iso, local_date_of
from app.web.security import COOKIE, LocalOnlyMiddleware, check_token, ensure_admin_token, make_session
from app.worker import jobs
from app.worker.scheduler import is_paused, set_paused

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
MAX_UPLOAD = 5 * 1024 * 1024
PAGE = 50


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or get_settings()
    clock = clock or Clock()
    for mode in (Mode.PUBLIC, Mode.TEST):
        init_db(mode, settings)
    ensure_admin_token(settings.data_dir)
    app = FastAPI(title="Social Eagle Community Manager", docs_url=None, redoc_url=None)
    app.add_middleware(LocalOnlyMiddleware, data_dir=settings.data_dir)
    app.state.settings, app.state.clock = settings, clock

    def mode_of(request: Request) -> Mode:
        raw = request.query_params.get("mode") or request.cookies.get("se_mode") or "public"
        try:
            mode = Mode(raw)
        except ValueError as exc:
            raise HTTPException(400, "unknown mode") from exc
        if mode is Mode.PRIVATE:
            raise HTTPException(403, "Private mode is deferred until the owner authorizes it.")
        return mode

    def eng(request: Request):
        return get_engine(mode_of(request), settings)

    def communities(s) -> list[m.Community]:
        return list(s.scalars(select(m.Community).order_by(m.Community.id)))

    def pick_community(s, request: Request) -> m.Community | None:
        cs = communities(s)
        cid = request.query_params.get("community")
        if cid:
            return next((c for c in cs if str(c.id) == cid), None)
        return next((c for c in cs if c.expected_sources), cs[0] if cs else None)

    def pick_date(request: Request) -> date:
        raw = request.query_params.get("date")
        return date.fromisoformat(raw) if raw else local_date_of(clock.now()) - timedelta(days=1)

    def page(request: Request, name: str, **ctx) -> HTMLResponse:
        mode = mode_of(request)
        with session_scope(eng(request)) as s:
            cs = communities(s)
            paused = is_paused(s)
        resp = TEMPLATES.TemplateResponse(request, name, {
            "mode": mode.value, "communities": cs, "paused": paused, "fmt_local": fmt_local, "json": json, **ctx})
        if request.query_params.get("mode"):
            resp.set_cookie("se_mode", mode.value, httponly=True, samesite="strict")
        return resp

    def report_for(request: Request):
        with session_scope(eng(request)) as s:
            c = pick_community(s, request)
            if c is None:
                return None, None
            d = pick_date(request)
            return c, build_report(s, c, d, d, clock.now(), settings)

    # ------------------------------------------------------------ auth
    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        return TEMPLATES.TemplateResponse(request, "login.html", {"error": None})

    @app.post("/login")
    def login(request: Request, token: str = Form(...)):
        if not check_token(settings.data_dir, token):
            return TEMPLATES.TemplateResponse(request, "login.html", {"error": "Invalid token"}, status_code=401)
        r = RedirectResponse("/", status_code=303)
        r.set_cookie(COOKIE, make_session(settings.data_dir), httponly=True, samesite="strict")
        return r

    @app.post("/logout")
    def logout():
        r = RedirectResponse("/login", status_code=303)
        r.delete_cookie(COOKIE)
        return r

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    # ------------------------------------------------------------ pages
    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request):
        c, p = report_for(request)
        with session_scope(eng(request)) as s:
            hb = s.get(m.AppState, "worker_heartbeat")
            recent = s.scalars(select(m.ReportRun).order_by(m.ReportRun.id.desc()).limit(5)).all()
            outbox = s.scalars(select(m.OutboxMessage).order_by(m.OutboxMessage.id.desc()).limit(5)).all()
            runs = s.scalars(select(m.SyncRun).order_by(m.SyncRun.id.desc()).limit(8)).all()
        return page(request, "overview.html", c=c, p=p, heartbeat=hb.value if hb else None, recent=recent,
                    outbox=outbox, runs=runs, date=pick_date(request))

    @app.get("/members", response_class=HTMLResponse)
    def members(request: Request, q: str = "", role: str = "", offset: int = 0):
        with session_scope(eng(request)) as s:
            c = pick_community(s, request)
            stmt = select(m.Member).where(m.Member.community_id == (c.id if c else -1))
            if q:
                stmt = stmt.where(or_(m.Member.display_name.ilike(f"%{q}%"), m.Member.source_member_id.ilike(f"%{q}%")))
            if role:
                stmt = stmt.where(m.Member.role == role)
            total = s.scalar(select(func.count()).select_from(stmt.subquery()))
            rows = s.scalars(stmt.order_by(m.Member.display_name).offset(max(offset, 0)).limit(PAGE)).all()
        _, p = report_for(request)
        status: dict[int, list[dict]] = {}
        if p and p["sections"]["learning"]["availability"] != "unavailable":
            for r in p["sections"]["learning"]["enrolments"]:
                status.setdefault(r["member"]["member_id"], []).append(r)
        return page(request, "members.html", c=c, rows=rows, total=total, q=q, role=role, offset=offset, page_size=PAGE,
                    learning=status)

    @app.get("/members/{member_id}", response_class=HTMLResponse)
    def member_detail(request: Request, member_id: int):
        with session_scope(eng(request)) as s:
            mem = s.get(m.Member, member_id)
            if mem is None:
                raise HTTPException(404)
            ev = build_member_evidence(s, member_id, clock.now())
            notes = s.scalars(select(m.MemberNote).where(m.MemberNote.member_id == member_id)
                              .order_by(m.MemberNote.created_at.desc())).all()
        return page(request, "member.html", mem=mem, ev=ev, notes=notes)

    @app.post("/members/{member_id}/notes")
    def add_note(request: Request, member_id: int, text: str = Form(..., max_length=2000)):
        with session_scope(eng(request)) as s:
            if s.get(m.Member, member_id) is None:
                raise HTTPException(404)
            s.add(m.MemberNote(member_id=member_id, text=text, author="admin", created_at=clock.now()))
        return RedirectResponse(f"/members/{member_id}", status_code=303)

    @app.post("/members/{member_id}/corrections")
    def correct_member(request: Request, member_id: int, field: str = Form(...), value: str = Form(...),
                       reason: str = Form(..., min_length=3)):
        if field not in ("display_name", "role"):
            raise HTTPException(400, "field not correctable")
        if field == "role" and value not in ("member", "staff", "bot", "admin"):
            raise HTTPException(400, "invalid role")
        with session_scope(eng(request)) as s:
            mem = s.get(m.Member, member_id)
            if mem is None:
                raise HTTPException(404)
            s.add(m.AuditLog(entity_type="member", entity_id=member_id, field=field, old_value=getattr(mem, field),
                             new_value=value, reason=reason, actor="admin", at=clock.now()))
            setattr(mem, field, value)
        return RedirectResponse(f"/members/{member_id}", status_code=303)

    @app.get("/members/{member_id}/evidence")
    def member_evidence(request: Request, member_id: int, format: str = "html"):
        with session_scope(eng(request)) as s:
            if s.get(m.Member, member_id) is None:
                raise HTTPException(404)
            ev = build_member_evidence(s, member_id, clock.now())
        if format == "json":
            return JSONResponse(ev, headers={"Content-Disposition": f'attachment; filename="member-{member_id}-evidence.json"'})
        return HTMLResponse(render_member_html(ev))

    for section in ("learning", "participation", "assignments", "wins", "support", "leaderboard"):
        def _view(request: Request, _section=section):
            c, p = report_for(request)
            return page(request, f"section_{_section}.html", c=c, p=p, date=pick_date(request), section=_section)
        app.add_api_route(f"/{section}", _view, methods=["GET"], response_class=HTMLResponse, name=section)

    @app.get("/health", response_class=HTMLResponse)
    def health(request: Request):
        c, p = report_for(request)
        now = clock.now()
        with session_scope(eng(request)) as s:
            runs = s.scalars(select(m.SyncRun).order_by(m.SyncRun.id.desc()).limit(40)).all()
            q = jobs.queue_health(s, now)
            failed_jobs = s.scalars(select(m.Job).where(m.Job.status == "failed")).all()
            events = s.scalars(select(m.SchedulerEvent).order_by(m.SchedulerEvent.id.desc()).limit(30)).all()
            hb = s.get(m.AppState, "worker_heartbeat")
            stale = [tuple(r) for r in s.execute(
                select(m.Course.title, func.max(m.ProgressSnapshot.observed_at))
                .join(m.Course, m.Course.id == m.ProgressSnapshot.course_id)
                .group_by(m.Course.title)).all()] if c else []
        return page(request, "health.html", c=c, p=p, runs=runs, queue=q, failed_jobs=failed_jobs, events=events,
                    heartbeat=hb.value if hb else None, now=now, date=pick_date(request), stale=stale)

    @app.get("/reports", response_class=HTMLResponse)
    def reports(request: Request):
        with session_scope(eng(request)) as s:
            rows = s.scalars(select(m.ReportRun).order_by(m.ReportRun.report_date.desc(), m.ReportRun.revision.desc())
                             .limit(100)).all()
            c = pick_community(s, request)
        return page(request, "reports.html", rows=rows, c=c, date=pick_date(request))

    @app.post("/reports/run")
    def run_report(request: Request, first: str = Form(...), last: str = Form(""), community: int = Form(...)):
        d1 = date.fromisoformat(first)
        d2 = date.fromisoformat(last) if last else d1
        if d2 < d1 or (d2 - d1).days > 62:
            raise HTTPException(400, "range must be 1–62 days")
        with session_scope(eng(request)) as s:
            c = s.get(m.Community, community)
            if c is None:
                raise HTTPException(404)
            rr, _created = issue_report(s, c, d1, d2, clock.now(), settings, trigger="manual")
            rid = rr.id
        return RedirectResponse(f"/reports/{rid}", status_code=303)

    @app.get("/reports/preview", response_class=HTMLResponse)
    def preview(request: Request, first: str, last: str = "", community: int = 0):
        d1 = date.fromisoformat(first)
        d2 = date.fromisoformat(last) if last else d1
        with session_scope(eng(request)) as s:
            c = s.get(m.Community, community) or pick_community(s, request)
            if c is None:
                raise HTTPException(404)
            p = build_report(s, c, d1, d2, clock.now(), settings)
        return HTMLResponse('<div style="background:#ffe9a8;padding:6px 12px;font:14px sans-serif"><b>PREVIEW</b> — '
                            "not issued, not stored, not delivered.</div>" + render_html(p))

    @app.get("/reports/{rid}", response_class=HTMLResponse)
    def report_view(request: Request, rid: int):
        with session_scope(eng(request)) as s:
            rr = s.get(m.ReportRun, rid)
            if rr is None:
                raise HTTPException(404)
            newer = s.scalar(select(m.ReportRun).where(m.ReportRun.supersedes_id == rid))
            banner = ""
            if newer:
                banner = (f'<div style="background:#fff3f4;padding:6px 12px;font:14px sans-serif">Superseded by '
                          f'<a href="/reports/{newer.id}">revision {newer.revision}</a>.</div>')
            return HTMLResponse(banner + render_html(rr.payload, rr))

    @app.get("/reports/{rid}/download/{fmt}")
    def report_download(request: Request, rid: int, fmt: str):
        with session_scope(eng(request)) as s:
            rr = s.get(m.ReportRun, rid)
            if rr is None:
                raise HTTPException(404)
            name = f"report-{rr.report_date}-r{rr.revision}"
            if fmt == "json":
                return Response(json.dumps(rr.payload, indent=2, default=str), media_type="application/json",
                                headers={"Content-Disposition": f'attachment; filename="{name}.json"'})
            if fmt == "csv":
                return PlainTextResponse(render_csv(rr.payload), media_type="text/csv",
                                         headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
        raise HTTPException(400)

    @app.get("/search", response_class=HTMLResponse)
    def search(request: Request, q: str = "", member: int | None = None):
        results: list[dict] = []
        posts: list[m.Post] = []
        if q:
            with session_scope(eng(request)) as s:
                rebuild_index(s)
                results = search_lessons(s, q, member, clock.now())
                posts = list(s.scalars(select(m.Post).where(or_(m.Post.title.ilike(f"%{q}%"),
                                                                    m.Post.excerpt.ilike(f"%{q}%"))).limit(25)))
        return page(request, "search.html", q=q, member=member, results=results, posts=posts)

    @app.get("/lessons/{lesson_id}", response_class=HTMLResponse)
    def lesson(request: Request, lesson_id: int):
        with session_scope(eng(request)) as s:
            lsn = s.get(m.Lesson, lesson_id)
            if lsn is None:
                raise HTTPException(404)
            course = s.get(m.Course, lsn.course_id)
        return page(request, "lesson.html", lesson=lsn, course=course)

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request):
        return page(request, "settings.html", settings=settings, calc_version=CALC_VERSION)

    @app.post("/settings/pause")
    def pause(request: Request, paused: str = Form(...)):
        with session_scope(eng(request)) as s:
            set_paused(s, paused == "1")
        return RedirectResponse("/settings", status_code=303)

    @app.post("/import")
    async def import_bundle(request: Request, file: UploadFile):
        mode = mode_of(request)
        raw = await file.read(MAX_UPLOAD + 1)
        if len(raw) > MAX_UPLOAD:
            raise HTTPException(413, "file too large")
        try:
            data = json.loads(raw)
            with session_scope(eng(request)) as s:
                run = ingest_bundle(s, data, mode, clock.now())
                out = {"sync_run_id": run.id, "status": run.status, "new": run.records_new, "changed": run.records_changed}
        except (json.JSONDecodeError, ValidationError, ImportRejected, PrivateModeDisabled) as exc:
            raise HTTPException(422, f"import rejected: {str(exc)[:500]}") from exc
        return out

    @app.post("/public/sync")
    def public_sync(request: Request):
        if mode_of(request) is not Mode.PUBLIC:
            raise HTTPException(400, "public sync runs only in public mode")
        from app.connectors.public_skool import DEFAULT_SOURCES, PublicReadConnector
        con = PublicReadConnector(settings)
        results = []
        for src in DEFAULT_SOURCES:
            b = con.fetch_bundle(src, clock.now())
            with session_scope(get_engine(Mode.PUBLIC, settings)) as s:
                run = ingest_bundle(s, b, Mode.PUBLIC, clock.now())
                results.append({"source": src.url, "status": run.status, "error": run.error, "new": run.records_new})
        return page(request, "sync_result.html", results=results)

    # ------------------------------------------------------------ JSON API
    @app.get("/api/members")
    def api_members(request: Request, limit: int = 50, offset: int = 0):
        limit = min(max(limit, 1), 200)
        with session_scope(eng(request)) as s:
            c = pick_community(s, request)
            rows = s.scalars(select(m.Member).where(m.Member.community_id == (c.id if c else -1))
                             .order_by(m.Member.id).offset(max(offset, 0)).limit(limit)).all()
            return {"items": [{"id": r.id, "source_member_id": r.source_member_id, "name": r.display_name,
                               "role": r.role} for r in rows], "limit": limit, "offset": offset}

    @app.get("/api/reports/preview")
    def api_preview(request: Request):
        _, p = report_for(request)
        if p is None:
            raise HTTPException(404, "no community in this workspace")
        return p

    @app.get("/api/health")
    def api_health(request: Request):
        with session_scope(eng(request)) as s:
            hb = s.get(m.AppState, "worker_heartbeat")
            return {"mode": mode_of(request).value, "queue": jobs.queue_health(s, clock.now()),
                    "worker_heartbeat": hb.value if hb else None, "now": iso(clock.now())}

    return app


app = None


def get_app() -> FastAPI:
    global app
    if app is None:
        app = create_app()
    return app
