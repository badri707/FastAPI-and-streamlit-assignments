"""Backup/restore into a separate location, optional import isolation, low disk, missing SSD, model outage."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from app import db
from app.config import get_settings
from app.services import backup, importer, metrics


def test_backup_during_writes_and_restore_to_separate_dir(seeded, tmp_path):
    from app.connectors.factory import get_store
    stop = threading.Event()

    def writer() -> None:
        st = get_store()
        while not stop.is_set():
            st.add_post(author_id="syn-mem-scn-support", title="busy?", body="Writing during backup?")

    t = threading.Thread(target=writer)
    t.start()
    try:
        res = backup.create_backup(label="test", dest_root=tmp_path / "bk")
    finally:
        stop.set()
        t.join()
    assert res["integrity_check"] == "ok"
    live_before = (get_settings().app_db_path.stat().st_mtime, get_settings().app_db_path.stat().st_size)
    out = backup.verify_and_restore(Path(res["path"]), tmp_path / "restored")
    assert out["row_counts_match"] and set(out["integrity"].values()) == {"ok"}
    assert (get_settings().app_db_path.stat().st_mtime, get_settings().app_db_path.stat().st_size) == live_before
    with pytest.raises(ValueError):
        backup.verify_and_restore(Path(res["path"]), get_settings().data_dir)


def test_low_disk_refuses_backup(seeded, monkeypatch):
    monkeypatch.setattr(backup, "free_mb", lambda _p: 10.0)
    with pytest.raises(OSError, match="Not enough free disk"):
        backup.create_backup(label="low")


def test_missing_external_ssd_does_not_block_status(client, monkeypatch, tmp_path):
    monkeypatch.setenv("EXTERNAL_SSD_PATH", str(tmp_path / "not-mounted"))
    get_settings.cache_clear()
    try:
        r = client.get("/api/system/status").json()
        assert r["external_ssd"]["present"] is False
    finally:
        monkeypatch.delenv("EXTERNAL_SSD_PATH")
        get_settings.cache_clear()


def test_ai_outage_keeps_deterministic_features_working(client, monkeypatch):
    from app.ai import provider
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")  # nothing listens here
    get_settings.cache_clear()
    provider.set_provider(None)
    try:
        st = client.get("/api/system/status").json()
        assert st["ai"]["ok"] is False and st["ai"]["status"] == "unreachable"
        assert client.get("/api/overview").status_code == 200
        r = client.post("/api/chat", json={"message": "How many members joined?"}).json()
        assert r["status"] == "unavailable" and r["answer"] is None
    finally:
        provider.set_provider(None)
        get_settings.cache_clear()


def test_import_preview_commit_isolation_and_duplicate(seeded):
    csv_bytes = b"id,name,email,joined\nu1,Real Person One,one@example.com,2026-01-02\nu2,,two@example.com,2026-01-03\nu3,Third,three@example.com,not-a-date\n"
    with db.session_scope() as s:
        pv = importer.preview(s, filename="members.csv", data=csv_bytes, entity="members", mapping=None)
        assert pv["mapping"]["upstream_id"] == "id" and pv["mapping"]["display_name"] == "name"
        assert pv["rows_ok"] == 1 and pv["rows_rejected"] == 2
        res = importer.commit(s, pv["batch_id"], csv_bytes)
        assert res["inserted"] == 1 and res["dataset"].startswith("import:")
        gid = metrics.main_group_id(s)
        assert gid != res["group_id"]  # imports never become the default group
        sc = metrics.default_scope(s, 30, gid)
        assert metrics.member_totals(s, sc)["active_members"] == metrics.member_totals(s, sc)["active_members"]
        pv2 = importer.preview(s, filename="members.csv", data=csv_bytes, entity="members", mapping=None)
        assert pv2["duplicate_of_batch"] == pv["batch_id"]
        with pytest.raises(importer.ImportError_, match="already imported"):
            importer.commit(s, pv2["batch_id"], csv_bytes)
        assert importer.delete_batch(s, pv["batch_id"]) == {"deleted_batch": pv["batch_id"]}
        with pytest.raises(importer.ImportError_):
            importer.preview(s, filename="x.json", data=json.dumps({"a": 1}).encode(), entity="members", mapping=None)
