from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import fixtures as fx
from app import models as m
from app.db import session_scope
from app.reports.daily import csv_safe
from app.timeutil import FrozenClock
from app.web.main import create_app
from app.web.security import ensure_admin_token


@pytest.fixture
def client(seeded, settings):
    app = create_app(settings, FrozenClock(fx.at("2026-10-20 09:30")))
    c = TestClient(app)
    tok, _ = ensure_admin_token(settings.data_dir)
    r = c.post("/login", data={"token": tok}, follow_redirects=False)
    assert r.status_code == 303
    c.cookies.set("se_mode", "test")
    return c


def test_requires_login_and_loopback(settings):
    app = create_app(settings)
    c = TestClient(app)
    assert c.get("/", follow_redirects=False).status_code == 303
    assert c.get("/api/health").status_code == 401
    assert c.post("/login", data={"token": "wrong"}).status_code == 401
    assert c.get("/healthz", headers={"host": "evil.example"}).status_code == 400


def test_all_pages_render_with_synthetic_banner(client):
    for path in ["/", "/members", "/learning", "/participation", "/assignments", "/wins", "/support", "/leaderboard",
                 "/health", "/reports", "/settings", "/search?q=pixel"]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert "TEST WORKSPACE" in r.text, path
    assert "Pixel not firing" in client.get("/support").text
    assert "unknown" in client.get("/learning").text


def test_private_mode_refused(client):
    assert client.get("/?mode=private").status_code == 403


def test_run_now_preview_revision_and_downloads(client, seeded):
    assert "PREVIEW" in client.get("/reports/preview?first=2026-10-19").text
    with session_scope(seeded) as s:
        cid = s.scalar(select(m.Community)).id
        assert s.scalar(select(m.ReportRun)) is None  # preview stored nothing
    r = client.post("/reports/run", data={"first": "2026-10-19", "community": cid}, follow_redirects=False)
    rid = int(r.headers["location"].rsplit("/", 1)[1])
    r2 = client.post("/reports/run", data={"first": "2026-10-19", "community": cid}, follow_redirects=False)
    assert r2.headers["location"].endswith(f"/{rid}")  # identical re-run → same report
    page = client.get(f"/reports/{rid}").text
    assert "Revision</b> 1" in page and "complete" in page
    csv = client.get(f"/reports/{rid}/download/csv").text
    assert "participation,posts,8" in csv
    data = client.get(f"/reports/{rid}/download/json").json()
    assert data["interval"]["timezone"] == "Asia/Kolkata"


def test_member_detail_notes_corrections_evidence(client, seeded):
    with session_scope(seeded) as s:
        mid = s.scalar(select(m.Member).where(m.Member.source_member_id == "m-dev")).id
    assert "Pixel not firing" in client.get(f"/members/{mid}").text
    client.post(f"/members/{mid}/notes", data={"text": "Called member <script>x</script>"})
    page = client.get(f"/members/{mid}").text
    assert "&lt;script&gt;" in page and "<script>x" not in page  # escaped
    client.post(f"/members/{mid}/corrections", data={"field": "display_name", "value": "Dev K.", "reason": "member request"})
    ev = client.get(f"/members/{mid}/evidence?format=json").json()
    assert ev["member"]["name"] == "Dev K." and ev["corrections"][0]["old"] == "Dev"
    assert "Evidence report" in client.get(f"/members/{mid}/evidence").text


def test_pause_toggle_and_import_validation(client):
    client.post("/settings/pause", data={"paused": "1"})
    assert "Automation paused" in client.get("/settings").text
    bad = client.post("/import", files={"file": ("b.json", b'{"format":"nope"}', "application/json")})
    assert bad.status_code == 422
    ok = client.post("/import", files={"file": ("b.json", json.dumps(fx.progress_bundle()).encode(), "application/json")})
    assert ok.status_code == 200 and ok.json()["new"] == 0  # already ingested → idempotent


def test_cross_origin_post_refused(client):
    r = client.post("/settings/pause", data={"paused": "1"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403


def test_lesson_search_permission_scope(client, seeded):
    with session_scope(seeded) as s:
        vik = s.scalar(select(m.Member).where(m.Member.source_member_id == "m-vikram")).id
    assert "No permitted lesson matches" in client.get(f"/search?q=high-ticket&member={vik}").text
    assert "VIP" in client.get("/search?q=high-ticket").text  # admin scope


def test_csv_formula_injection_neutralised():
    assert csv_safe("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert csv_safe("+1") == "'+1" and csv_safe("ok") == "ok"


def test_null_origin_refused_and_same_origin_allowed(client):
    assert client.post("/settings/pause", data={"paused": "1"}, headers={"origin": "null"}).status_code == 403
    ok = client.post("/settings/pause", data={"paused": "0"}, headers={"origin": "http://127.0.0.1:8765"},
                     follow_redirects=False)
    assert ok.status_code == 303
    assert client.get("/settings").headers["referrer-policy"] == "same-origin"


def test_community_simulator_and_bot_end_to_end(client, seeded):
    assert client.get("/community").status_code == 200
    client.post("/community/act-as", data={"member": "m-dev", "back": "/community"})
    r = client.post("/community/post", data={"category": "Questions",
                                             "title": "How do I install the Meta pixel before conversion campaigns?",
                                             "body": "Stuck on lesson 3"}, follow_redirects=False)
    thread_url = r.headers["location"]
    assert "Question register" in client.get(thread_url).text
    client.post("/bot/run", data={"back": thread_url})
    page = client.get(thread_url).text
    assert "EagleBot" in page and "Facebook ads basics" in page and "answered" in page
    # owner escalation through the UI
    r = client.post("/community/post", data={"category": "Questions", "title": "Can I get a refund?", "body": ""},
                    follow_redirects=False)
    client.post("/bot/run", data={})
    inbox = client.get("/bot").text
    assert "Owner inbox" in inbox and "refund request" in inbox
    with session_scope(seeded) as s:
        q = s.scalar(select(m.SupportQuestion).where(m.SupportQuestion.state == "awaiting_owner"))
        qid = q.id
    client.post(f"/bot/question/{qid}/answer", data={"answer": "Please email support — refunds follow the policy.",
                                                     "staff": "s-coach"})
    with session_scope(seeded) as s:
        assert s.get(m.SupportQuestion, qid).state == "answered"
    client.post(f"/bot/question/{qid}/resolved", data={})
    with session_scope(seeded) as s:
        assert s.get(m.SupportQuestion, qid).state == "closed"


def test_simulator_refused_in_public_mode(client):
    client.cookies.set("se_mode", "public")
    assert client.get("/community").status_code == 400
    assert client.post("/bot/run", data={}).status_code == 400


def test_synthetic_thread_links_work(client):
    r = client.get("/test/thread/p-dev-q", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/community/post/")
