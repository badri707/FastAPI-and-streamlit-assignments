from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app import fixtures as fx
from app import models as m
from app.bootstrap import init_db
from app.config import ExternalWriteDisabled, Mode, PrivateModeDisabled
from app.connectors.importer import ImportRejected, ingest_bundle
from app.connectors.public_skool import PublicReadConnector, PublicSource, UnsafeURL, validate_url
from app.connectors.registry import get_connector
from app.db import get_engine, session_scope

HTML = (Path(__file__).parent / "fixtures" / "public_group_structure_SYNTHETIC.html").read_text()
SRC = PublicSource("example-group", "https://www.skool.com/example-group", "Example (synthetic)")
NOW = fx.at("2026-10-20 10:00")


class Spy:
    def __init__(self, routes):
        self.routes, self.requests = routes, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.url.host, request.url.path)
        return self.routes.get(key, httpx.Response(404))


def connector(settings, routes):
    spy = Spy(routes)
    return PublicReadConnector(settings, transport=httpx.MockTransport(spy), sleep=lambda s: None), spy


ROBOTS_OK = httpx.Response(200, text="User-agent: *\nAllow: /\n")


def test_public_page_becomes_records_and_refresh_does_not_duplicate(settings, monkeypatch):
    monkeypatch.setenv("SKOOL_PASSWORD", "should-never-be-used")
    monkeypatch.setenv("SKOOL_COOKIE", "session=abc")
    init_db(Mode.PUBLIC, settings)
    eng = get_engine(Mode.PUBLIC, settings)
    con, spy = connector(settings, {("www.skool.com", "/robots.txt"): ROBOTS_OK,
                                    ("www.skool.com", "/example-group"): httpx.Response(200, text=HTML)})
    b = con.fetch_bundle(SRC, NOW)
    assert b.get("status") != "failed", b
    with session_scope(eng) as s:
        run = ingest_bundle(s, b, Mode.PUBLIC, NOW)
        assert run.coverage_status == "partial" and run.records_new >= 3
    with session_scope(eng) as s:
        run2 = ingest_bundle(s, con.fetch_bundle(SRC, NOW), Mode.PUBLIC, NOW)
        assert run2.records_new == 0
        assert s.scalar(select(func.count()).select_from(m.Post)) == 3
        c = s.scalar(select(m.Community))
        assert (c.displayed_member_total, c.displayed_online, c.is_company_community) == ("12.3k", "1.4k", False)
        relative = s.scalar(select(m.Post).where(m.Post.source_post_id == "p-3"))
        assert relative.created_at is None and relative.timestamp_precision == "unknown"
        assert relative.displayed_value == "yesterday"
        assert all(p.is_excerpt for p in s.scalars(select(m.Post)))
    for r in spy.requests:
        assert r.method == "GET"
        assert "authorization" not in r.headers and "cookie" not in r.headers


def test_login_wall_and_denials_are_failures_not_empty(settings):
    for resp in (httpx.Response(302, headers={"Location": "https://www.skool.com/login?next=/example-group"}),
                 httpx.Response(403), httpx.Response(200, text="<html>Please log in to continue</html>")):
        con, _ = connector(settings, {("www.skool.com", "/robots.txt"): ROBOTS_OK,
                                      ("www.skool.com", "/example-group"): resp})
        b = con.fetch_bundle(SRC, NOW)
        assert b["status"] == "failed" and "AccessDenied" in b["error"]


def test_redirect_to_other_host_rejected(settings):
    con, spy = connector(settings, {("www.skool.com", "/robots.txt"): ROBOTS_OK,
                                    ("www.skool.com", "/example-group"):
                                        httpx.Response(302, headers={"Location": "https://evil.example/steal"})})
    b = con.fetch_bundle(SRC, NOW)
    assert b["status"] == "failed" and "redirect rejected" in b["error"]
    assert all(r.url.host == "www.skool.com" for r in spy.requests)


def test_robots_disallow_respected(settings):
    con, spy = connector(settings, {("www.skool.com", "/robots.txt"):
                                        httpx.Response(200, text="User-agent: *\nDisallow: /\n")})
    b = con.fetch_bundle(SRC, NOW)
    assert b["status"] == "failed" and "robots" in b["error"]
    assert [r.url.path for r in spy.requests] == ["/robots.txt"]


def test_parse_failure_is_reported(settings):
    con, _ = connector(settings, {("www.skool.com", "/robots.txt"): ROBOTS_OK,
                                  ("www.skool.com", "/example-group"): httpx.Response(200, text="<html>changed</html>")})
    b = con.fetch_bundle(SRC, NOW)
    assert b["status"] == "failed" and "ParseFailed" in b["error"]


@pytest.mark.parametrize("url", ["http://www.skool.com/x", "https://evil.com/x", "https://www.skool.com:8443/x",
                                 "https://u:p@www.skool.com/x", "https://www.skool.com/login",
                                 "https://www.skool.com/x/settings", "https://169.254.169.254/latest"])
def test_unsafe_urls_rejected(url):
    with pytest.raises(UnsafeURL):
        validate_url(url)


def test_writes_disabled_in_every_mode(settings):
    for mode in (Mode.PUBLIC, Mode.TEST):
        con = get_connector(mode, settings)
        for action in ("post", "reply", "react", "message", "join_group"):
            with pytest.raises(ExternalWriteDisabled):
                getattr(con, action)("anything")
    with pytest.raises(PrivateModeDisabled):
        get_connector(Mode.PRIVATE, settings)
    with pytest.raises(PrivateModeDisabled):
        settings.db_path(Mode.PRIVATE)


def test_test_mode_sends_no_network_requests(seeded, settings, monkeypatch):
    sent = []
    real_send = httpx.Client.send
    monkeypatch.setattr(httpx.Client, "send", lambda self, req, **k: sent.append(req) or real_send(self, req, **k))
    from app.reports.daily import issue_report
    from app.timeutil import FrozenClock
    from app.worker.scheduler import tick
    from tests.conftest import community
    tick(Mode.TEST, FrozenClock(fx.at("2026-10-20 08:00")), settings)
    tick(Mode.TEST, FrozenClock(fx.at("2026-10-20 09:01")), settings)
    with session_scope(seeded) as s:
        issue_report(s, community(s), fx.at("2026-10-19 12:00").date(), fx.at("2026-10-19 12:00").date(),
                     fx.at("2026-10-20 10:00"), settings)
    with pytest.raises(RuntimeError):
        get_connector(Mode.TEST, settings).fetch_bundle()
    assert sent == []


def test_workspace_isolation(settings):
    init_db(Mode.PUBLIC, settings)
    with session_scope(get_engine(Mode.PUBLIC, settings)) as s:
        with pytest.raises(ImportRejected):
            ingest_bundle(s, fx.membership_bundle(), Mode.PUBLIC, NOW)  # synthetic → public refused
    public_like = fx.clone(fx.membership_bundle())
    public_like["community"] = {**public_like["community"], "is_synthetic": False, "slug": "public-x"}
    with session_scope(get_engine(Mode.TEST, settings)) as s:
        with pytest.raises(ImportRejected):
            ingest_bundle(s, public_like, Mode.TEST, NOW)
    assert settings.db_path(Mode.PUBLIC) != settings.db_path(Mode.TEST)


def test_group_without_recognised_posts_is_a_failure_not_success(settings):
    html = HTML.replace('"postTrees"', '"somethingElse"').replace('"metadata":{"title"', '"meta":{"title"')
    con, _ = connector(settings, {("www.skool.com", "/robots.txt"): ROBOTS_OK,
                                  ("www.skool.com", "/example-group"): httpx.Response(200, text=html)})
    b = con.fetch_bundle(SRC, NOW)
    assert b["status"] == "failed" and "no posts recognised" in b["error"]


def test_inspect_prints_structure_without_values(settings):
    from app.connectors.public_skool import inspect_cached_page
    con, _ = connector(settings, {("www.skool.com", "/robots.txt"): ROBOTS_OK,
                                  ("www.skool.com", "/example-group"): httpx.Response(200, text=HTML)})
    con.fetch_bundle(SRC, NOW)
    out = inspect_cached_page(settings.data_dir / "public_cache")
    assert "postTrees" in out and "Ada" not in out and "Welcome" not in out


def test_short_summary_finds_post_list_without_values(settings):
    from app.connectors.public_skool import short_summary
    con, _ = connector(settings, {("www.skool.com", "/robots.txt"): ROBOTS_OK,
                                  ("www.skool.com", "/example-group"): httpx.Response(200, text=HTML)})
    con.fetch_bundle(SRC, NOW)
    out = short_summary(settings.data_dir / "public_cache")
    assert "pageProps.postTrees" in out and "Ada" not in out and len(out.splitlines()) < 30
    print(out)
