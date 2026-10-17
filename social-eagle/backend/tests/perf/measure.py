"""Representative workload measurements against the RUNNING app (scripts/start). Writes docs/evidence/perf.json.

Usage: python -m tests.perf.measure --password ... [--burst 20]
Measures: API latency (p50/p95) for core endpoints at the seeded scale, RSS of API/worker/Ollama processes, incremental sync
cost, and a burst of N new questions processed end-to-end by the worker with the real local model (queue drain time, max age).
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
ENDPOINTS = ["/api/overview?days=30", "/api/members?page_size=50", "/api/members?q=Sharma", "/api/members?sort=last_contribution&desc=true",
             "/api/support?unanswered=true", "/api/posts", "/api/learning/courses", "/api/events", "/api/engagement?days=30",
             "/api/reports/summary?period=weekly", "/api/segments", "/api/learning/stalled", "/api/reports/export/daily",
             "/api/system/status"]


def rss_mb(pattern: str) -> float | None:
    out = subprocess.run(["ps", "-eo", "rss,args"], capture_output=True, text=True).stdout  # noqa: S603,S607
    vals = [int(line.split(None, 1)[0]) for line in out.splitlines()[1:] if pattern in line and "measure" not in line]
    return round(sum(vals) / 1024, 1) if vals else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8787")
    ap.add_argument("--user", default="owner")
    ap.add_argument("--password", required=True)
    ap.add_argument("--burst", type=int, default=20)
    ap.add_argument("--rounds", type=int, default=15)
    a = ap.parse_args()
    c = httpx.Client(base_url=a.base, trust_env=False, timeout=600)
    r = c.post("/api/auth/login", json={"username": a.user, "password": a.password})
    r.raise_for_status()
    c.headers["x-csrf-token"] = r.json()["csrf"]
    status = c.get("/api/system/status").json()
    lat = {}
    for ep in ENDPOINTS:
        samples = []
        for _ in range(a.rounds):
            t = time.perf_counter()
            assert c.get(ep).status_code == 200, ep
            samples.append((time.perf_counter() - t) * 1000)
        samples.sort()
        lat[ep] = {"p50_ms": round(statistics.median(samples), 1), "p95_ms": round(samples[int(0.95 * (len(samples) - 1))], 1),
                   "max_ms": round(samples[-1], 1)}
    mem_before = {"api": rss_mb("uvicorn app.main:app"), "worker": rss_mb("app.worker"), "ollama": rss_mb("ollama")}
    # incremental sync cost: 100 small events then one sync
    for i in range(100):
        c.post("/api/lab/reaction" if i % 2 else "/api/lab/progress",
               json={"post_upstream_id": "syn-post-scn-answered", "member_upstream_id": f"syn-mem-{(i % 200) + 1:04d}", "auto_sync": False}
               if i % 2 else {"member_upstream_id": f"syn-mem-{(i % 200) + 1:04d}", "lesson_upstream_id": "crs-onboarding-l1", "auto_sync": False})
    t = time.perf_counter()
    sync_res = c.post("/api/lab/sync-now").json()
    sync_ms = round((time.perf_counter() - t) * 1000, 1)
    # burst of new questions processed by the worker with the real model
    qs = ["How long should I run an ad test?", "Do short videos need captions?", "When are office hours?", "What should my welcome emails contain?",
          "How do I pick a niche?", "How often should I clean my email list?", "What CTR is too low?", "How fast can I scale a winning ad?",
          "What gear do I need for reels?", "How should I name UTM parameters?"]
    t0 = time.time()
    ids = []
    for i in range(a.burst):
        rec = c.post("/api/lab/question", json={"member_upstream_id": "syn-mem-scn-samename-a", "title": f"Perf q{i}: {qs[i % len(qs)]}",
                                                "body": qs[i % len(qs)], "auto_sync": i == a.burst - 1}).json()
        ids.append(rec["simulator_record"]["upstream_id"])
    max_age, peak_rss = 0.0, mem_before.copy()
    done = 0
    while time.time() - t0 < 3600:
        acts = c.get("/api/actions", params={"page_size": 200}).json()["rows"]
        mine = [x for x in acts if x["target_upstream_id"] in ids]
        done = sum(1 for x in mine if x["state"] in ("verified", "sent", "drafted", "held", "cancelled"))
        q = c.get("/api/system/status").json()["queue"]
        max_age = max(max_age, q.get("oldest_queued_age_s") or 0)
        for k, pat in (("api", "uvicorn app.main:app"), ("worker", "app.worker"), ("ollama", "ollama")):
            v = rss_mb(pat)
            if v and (peak_rss.get(k) or 0) < v:
                peak_rss[k] = v
        if done >= a.burst:
            break
        time.sleep(5)
    drain_s = round(time.time() - t0, 1)
    acts = [x for x in c.get("/api/actions", params={"page_size": 200}).json()["rows"] if x["target_upstream_id"] in ids]
    diag = c.get("/api/system/diagnostics").json()
    out = {
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "environment": {"note": "Build container: x86_64, 4 vCPU, ~16 GB RAM, no GPU. NOT the owner's MacBook Air M2 (8 GB). "
                                "Re-run on the Mac before drawing capacity conclusions.", "platform": status["platform"],
                        "model": status["ai"].get("model"), "num_ctx": status["ai"].get("num_ctx")},
        "dataset": {"members": None},
        "api_latency": lat, "memory_rss_mb_before": mem_before, "memory_rss_mb_peak_during_burst": peak_rss,
        "incremental_sync": {"events": 100, "wall_ms": sync_ms, "result": {k: sync_res.get(k) for k in ("status", "applied", "pages")}},
        "question_burst": {"n": a.burst, "processed": done, "drain_seconds": drain_s, "max_queue_age_s": round(max_age, 1),
                           "states": {s: sum(1 for x in acts if x["state"] == s) for s in {x["state"] for x in acts}},
                           "answer_statuses": {s: sum(1 for x in acts if x["answer_status"] == s) for s in {x["answer_status"] for x in acts}}},
        "ai_latency_ms_recent": diag["ai_latency_ms"],
    }
    p = ROOT / "docs" / "evidence" / "perf.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
