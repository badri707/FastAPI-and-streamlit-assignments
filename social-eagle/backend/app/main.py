"""FastAPI application: API + built frontend on the same loopback origin."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import PROJECT_ROOT, get_settings
from .security import SAFE_METHODS, ensure_enrollment_token, host_allowed

log = logging.getLogger("app")
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def create_app() -> FastAPI:
    s = get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        from .migrate import upgrade

        upgrade(s.app_db_path)
        if ensure_enrollment_token():
            log.warning("No admin account yet. One-time enrollment token written to %s", s.data_dir / "enrollment.token")
        yield

    app = FastAPI(title="Social Eagle Community Manager", version="0.1.0", lifespan=lifespan,
                  description="Independent evaluation build. RUN_MODE=evaluation uses synthetic data and a local simulator.")

    @app.middleware("http")
    async def guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        if not host_allowed(request.headers.get("host")):
            return JSONResponse({"detail": "Host not allowed"}, status_code=400)
        if request.method not in SAFE_METHODS and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin is not None:
                o_host = origin.split("://", 1)[-1]
                if not host_allowed(o_host) or o_host != request.headers.get("host"):
                    return JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)
        resp: Response = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        resp.headers["X-Run-Mode"] = s.run_mode
        return resp

    from .api import (
        actions_api,
        auth_api,
        automation_api,
        chat_api,
        data_api,
        discussions_api,
        knowledge_api,
        lab_api,
        learning_api,
        members_api,
        reports_api,
        system_api,
    )

    for r in (auth_api, system_api, members_api, discussions_api, knowledge_api, actions_api, automation_api, chat_api,
              learning_api, reports_api, data_api, lab_api):
        app.include_router(r.router)

    if FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> Response:
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not found"}, status_code=404)
            f = (FRONTEND_DIST / path).resolve()
            if path and f.is_file() and FRONTEND_DIST.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()


def run() -> None:
    import uvicorn

    s = get_settings()
    if s.host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("Refusing to bind to a non-loopback address in this phase (remote access is disabled).")
    uvicorn.run("app.main:app", host=s.host, port=s.port, log_level="info", proxy_headers=False)


if __name__ == "__main__":
    run()
