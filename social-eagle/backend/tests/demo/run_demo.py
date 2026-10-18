"""Required acceptance demonstration against the RUNNING app (scripts/start). Writes docs/evidence/demo.json.

1. Add a new synthetic question (Evaluation lab API).
2. The worker generates a source-grounded answer with the real local model and publishes it in the local thread.
3. Kill the worker (SIGKILL, simulated crash); the supervisor restarts it. Replay the publish job. Confirm no duplicate reply.
4. Change a member's lesson progress and confirm the member profile and course report change.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
SIM = ROOT / "data" / "simulator.db"
APP = ROOT / "data" / "app.db"


def bot_replies(parent: str) -> int:
    c = sqlite3.connect(f"file:{SIM}?mode=ro", uri=True)
    n = c.execute("SELECT COUNT(*) FROM sim_posts WHERE parent_id=? AND is_automated=1", (parent,)).fetchone()[0]
    c.close()
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--password", required=True)
    ap.add_argument("--base", default="http://127.0.0.1:8787")
    a = ap.parse_args()
    c = httpx.Client(base_url=a.base, trust_env=False, timeout=300)
    r = c.post("/api/auth/login", json={"username": "owner", "password": a.password})
    r.raise_for_status()
    c.headers["x-csrf-token"] = r.json()["csrf"]
    steps = []

    def step(name: str, expected: str, actual: str, ok: bool, **extra: object) -> None:
        steps.append({"step": name, "expected": expected, "actual": actual, "pass": ok, **extra})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {actual}", flush=True)

    q = c.post("/api/lab/question", json={"member_upstream_id": "syn-mem-scn-annual-asker", "title": f"Demo: email list cleaning ({int(time.time())})",
                                          "body": "How often should I remove subscribers who never open my emails?"}).json()
    post_up = q["simulator_record"]["upstream_id"]
    step("1. add synthetic question", "question stored in simulator and synced", f"{post_up}; sync {q['sync']['status']}", q["sync"]["ok"])
    t0 = time.time()
    action = None
    while time.time() - t0 < 900:
        rows = [x for x in c.get("/api/actions", params={"page_size": 100}).json()["rows"] if x["target_upstream_id"] == post_up]
        if rows and rows[0]["state"] in ("verified", "sent", "drafted", "held", "cancelled", "failed"):
            action = c.get(f"/api/actions/{rows[0]['id']}").json()
            break
        time.sleep(3)
    took = round(time.time() - t0, 1)
    if action is None:
        step("2. grounded answer generated", "AI answer with citation", "timed out", False)
        return 1
    cites = [x["title"] for x in action["payload"].get("citations", [])]
    step("2. grounded answer generated", "status answered, cites Email Marketing lesson 5 (90 days)",
         f"answer_status={action['answer_status']}; cites={cites}; '90' in body={'90' in (action['body'] or '')}; {took}s",
         action["answer_status"] == "answered" and any("Email" in t for t in cites), body=action["body"], ai_run=action.get("ai_run"))
    path = "auto-published by the evaluation rule"
    if action["state"] in ("drafted", "held"):
        # The policy held it for review (e.g. an unconfirmed conflict). Approve it as the owner would in the review queue.
        path = f"held for review ({action.get('auto_blocked_reason') or action['answer_status']}); approved by owner"
        c.post(f"/api/actions/{action['id']}/approve").raise_for_status()
        for _ in range(120):
            time.sleep(2)
            action = c.get(f"/api/actions/{action['id']}").json()
            if action["state"] in ("verified", "failed", "cancelled", "held"):
                break
    thread = c.get("/api/posts", params={"q": "Demo email list cleaning", "page_size": 100}).json()
    pid = next((p["id"] for p in thread["rows"] if p["upstream_id"] == post_up), None)
    t = c.get(f"/api/threads/{pid}").json() if pid else {"thread": {"children": []}}
    visible = any(ch["is_automated"] for ch in t["thread"]["children"])
    step("3. published in local thread", "state verified; automated reply visible in thread; exactly 1 bot reply in simulator",
         f"path: {path}; state={action['state']}; visible={visible}; simulator bot replies={bot_replies(post_up)}",
         action["state"] == "verified" and visible and bot_replies(post_up) == 1)
    state = json.loads((ROOT / "data" / "run" / "state.json").read_text())
    old_pid = state["pids"]["worker"]
    os.kill(old_pid, signal.SIGKILL)
    new_pid = None
    for _ in range(90):
        time.sleep(1)
        st = json.loads((ROOT / "data" / "run" / "state.json").read_text())
        if st["pids"].get("worker") not in (None, old_pid):
            new_pid = st["pids"]["worker"]
            break
    # Replay: re-queue the already-completed publish job as if a restart had lost track of it.
    con = sqlite3.connect(APP)
    key = con.execute("SELECT idempotency_key, payload_version FROM actions WHERE id=?", (action["id"],)).fetchone()
    con.execute("UPDATE jobs SET status='queued', run_after='2000-01-01 00:00:00.000000', attempts=0 WHERE dedupe_key=?",
                (f"publish:{key[0]}:v{key[1]}",))
    con.commit()
    con.close()
    time.sleep(20)
    hb = c.get("/api/system/status").json()["worker"]
    step("4. worker crash + restart + job replay", "worker restarted by supervisor; replayed publish is a no-op; still exactly 1 reply",
         f"old pid {old_pid} → new pid {new_pid}; worker {hb['state']}; simulator bot replies={bot_replies(post_up)}",
         new_pid is not None and hb["state"] == "alive" and bot_replies(post_up) == 1)
    mem = c.get("/api/members", params={"q": "Tanvi Krishnan"}).json()["rows"][0]
    before = c.get(f"/api/members/{mem['id']}").json()
    done = {ls["title"] for cc in before["progress"] if cc["accessible"] for ls in cc["lesson_states"] if ls["completed"]}
    cat = c.get("/api/lab/catalog").json()["lessons"]
    accessible = {ls["title"] for cc in before["progress"] if cc["accessible"] for ls in cc["lesson_states"]}
    lesson = next(x for x in cat if x["title"] in accessible and x["title"] not in done)
    course_id = next(x["course_id"] for x in c.get("/api/learning/courses").json()["courses"]
                     if lesson["upstream_id"].startswith(x["upstream_id"] + "-"))
    lesson_count = lambda: next(x["members_marked_complete"] for x in c.get(f"/api/learning/courses/{course_id}").json()["lessons"]  # noqa: E731
                                if x["upstream_id"] == lesson["upstream_id"])
    lc_before = lesson_count()
    c.post("/api/lab/progress", json={"member_upstream_id": "syn-mem-scn-annual-asker", "lesson_upstream_id": lesson["upstream_id"]}).raise_for_status()
    after = c.get(f"/api/members/{mem['id']}").json()
    lc_after = lesson_count()
    step("5. progress change reflected in reports", "lessons_marked_complete +1 on member profile; course report updated from same DB",
         f"{lesson['upstream_id']}: {before['profile']['lessons_marked_complete']} → {after['profile']['lessons_marked_complete']}; "
         f"course report: members marked complete for this lesson {lc_before} → {lc_after}",
         after["profile"]["lessons_marked_complete"] == before["profile"]["lessons_marked_complete"] + 1 and lc_after == lc_before + 1)
    out = {"run_at_utc": datetime.now(UTC).isoformat(), "all_passed": all(s["pass"] for s in steps), "steps": steps}
    (ROOT / "docs" / "evidence" / "demo.json").write_text(json.dumps(out, indent=2))
    print(json.dumps({"all_passed": out["all_passed"]}))
    return 0 if out["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
