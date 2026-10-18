"""Authentication, CSRF, host/origin checks, input validation and injection resistance through the HTTP API."""
from __future__ import annotations

import io

from fastapi.testclient import TestClient


def test_unauthenticated_and_csrf_and_host_checks(client: TestClient):
    anon = TestClient(client.app)
    assert anon.get("/api/overview").status_code == 401
    assert anon.get("/api/auth/status", headers={"host": "evil.example"}).status_code == 400
    no_csrf = client.post("/api/system/pause", json={"paused": True}, headers={"x-csrf-token": "wrong"})
    assert no_csrf.status_code == 403
    cross = client.post("/api/system/pause", json={"paused": True}, headers={"origin": "http://evil.example"})
    assert cross.status_code == 403
    ok = client.post("/api/system/pause", json={"paused": False})
    assert ok.status_code == 200
    r = client.get("/api/system/status")
    assert r.headers["content-security-policy"].startswith("default-src 'self'")
    assert r.headers["x-frame-options"] == "DENY"


def test_enrollment_is_single_use_and_no_default_credentials(client: TestClient, seeded):
    assert not (seeded / "enrollment.token").exists()
    r = client.post("/api/auth/enroll", json={"token": "anything-at-all", "username": "second-admin", "password": "another-long-pass"})
    assert r.status_code == 409
    for creds in (("admin", "admin"), ("admin", "password"), ("owner", "owner")):
        assert TestClient(client.app).post("/api/auth/login", json={"username": creds[0], "password": creds[1]}).status_code in (401, 429)


def test_login_rate_limited(client: TestClient):
    anon = TestClient(client.app)
    codes = [anon.post("/api/auth/login", json={"username": "ratelimit", "password": "nope"}).status_code for _ in range(7)]
    assert codes[:5] == [401] * 5 and 429 in codes[5:]


def test_validation_and_injection_inputs(client: TestClient):
    assert client.get("/api/members", params={"q": "' OR 1=1; DROP TABLE members;--"}).status_code == 200
    assert client.get("/api/members").json()["total"] == 250
    r = client.post("/api/knowledge/search", json={"query": 'NEAR(ads budget) OR "x" * AND -', "tier": "general"})
    assert r.status_code == 200
    assert client.get("/api/posts", params={"q": '") OR 1 --'}).status_code == 200
    assert client.post("/api/system/clock/advance", json={"advance_minutes": -5}).status_code == 422
    assert client.put("/api/system/settings", json={"dataset_selection": ["../../etc"]}).status_code == 400
    bad = client.post("/api/automation/rules", json={"name": "ban everyone", "trigger": "new_member", "action_kind": "bulk_member_message", "mode": "auto"})
    assert bad.status_code == 400


def test_upload_path_traversal_and_type_checks(client: TestClient):
    r = client.post("/api/knowledge/upload", files={"file": ("../../etc/passwd.md", io.BytesIO(b"# Title\n\nSome text about reels."), "text/markdown")},
                    data={"access_tiers": "*"})
    assert r.status_code == 200 and r.json()["doc_key"] == "file:passwd"
    assert client.post("/api/knowledge/upload", files={"file": ("x.exe", io.BytesIO(b"MZ"), "application/octet-stream")}).status_code == 400
    assert client.post("/api/knowledge/upload", files={"file": ("fake.pdf", io.BytesIO(b"not a pdf"), "application/pdf")}).status_code == 400


def test_csv_export_neutralises_formulas(client: TestClient):
    from app import db
    from app.models import Member
    with db.session_scope() as s:
        m = s.query(Member).filter_by(upstream_id="syn-mem-scn-new").one()
        m.display_name = '=HYPERLINK("http://evil.example","x")'
    body = client.get("/api/reports/export/members").text
    assert '\'=HYPERLINK' in body and "\n=HYPERLINK" not in body
    assert "SIMULATED" in body and "SYNTHETIC" in body


def test_lab_api_absent_outside_evaluation(client: TestClient, monkeypatch):
    from app.config import get_settings
    monkeypatch.setenv("RUN_MODE", "live")
    get_settings.cache_clear()
    try:
        assert client.get("/api/lab/state").status_code == 404
        assert client.post("/api/system/clock/advance", json={"advance_minutes": 5}).status_code == 403
    finally:
        monkeypatch.setenv("RUN_MODE", "evaluation")
        get_settings.cache_clear()


def test_core_pages_respond(client: TestClient):
    for p in ["/api/overview", "/api/members?segment_id=1", "/api/segments", "/api/support?unanswered=true", "/api/posts",
              "/api/learning/courses", "/api/learning/stalled", "/api/events", "/api/engagement", "/api/reports/summary?period=weekly",
              "/api/reports/support", "/api/actions", "/api/jobs", "/api/knowledge/docs", "/api/automation/rules", "/api/lab/state",
              "/api/lab/catalog", "/api/backups", "/api/import/batches", "/api/system/diagnostics", "/api/system/settings",
              "/api/metrics/definitions", "/api/support/topics"]:
        assert client.get(p).status_code == 200, p


def test_notes_tags_and_member_erasure_survive_resync(client: TestClient):
    mid = client.get("/api/members", params={"q": "Kavya Iyer"}).json()["rows"][0]["id"]
    assert client.post(f"/api/members/{mid}/notes", json={"body": "Prefers evening calls"}).status_code == 200
    assert client.post(f"/api/members/{mid}/tags", json={"tag": "mentor-candidate"}).json()["tags"] == ["mentor-candidate"]
    detail = client.get(f"/api/members/{mid}").json()
    assert detail["notes"][0]["body"] == "Prefers evening calls"
    assert client.post(f"/api/members/{mid}/erase").status_code == 200
    client.post("/api/lab/progress", json={"member_upstream_id": "syn-mem-scn-silent", "lesson_upstream_id": "crs-ailab-l1"})
    after = client.get(f"/api/members/{mid}").json()
    assert after["member"]["display_name"].startswith("Erased member") and after["notes"] == []


def test_post_search_ranks_matches_and_includes_new_posts(client: TestClient):
    r = client.post("/api/lab/question", json={"member_upstream_id": "syn-mem-scn-support", "title": "Zebra email question",
                                                "body": "A unique zebra email question for search."})
    assert r.status_code == 200
    rows = client.get("/api/posts", params={"q": "zebra email"}).json()["rows"]
    assert rows and rows[0]["title"] == "Zebra email question"
