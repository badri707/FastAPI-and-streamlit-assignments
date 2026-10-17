"""Real-model AI evaluation (scripts/ai-eval). Runs against a COPY of the evaluation database so live data is untouched.

Usage: python -m tests.ai_eval.run [--model se-qwen3-4b] [--only A01,C01]
Scoring per case: expected status AND required facts present AND forbidden strings absent AND (for answered) a citation
to an expected document. Analytics: correct tool, verified wording, and the deterministic truth value in the answer.
This is a small evaluation set, not a production accuracy guarantee.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def copy_db(src_dir: Path, dst_dir: Path) -> None:
    for name in ("app.db", "simulator.db"):
        s = sqlite3.connect(src_dir / name)
        d = sqlite3.connect(dst_dir / name)
        s.backup(d)
        s.close()
        d.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    live = ROOT / "data"
    tmp = Path(tempfile.mkdtemp(prefix="se-ai-eval-"))
    copy_db(live, tmp)
    os.environ["DATA_DIR"] = str(tmp)
    if args.model:
        os.environ["OLLAMA_MODEL"] = args.model
    from sqlalchemy import select

    from app import db
    from app.ai import chat
    from app.ai.answer import answer_question
    from app.ai.provider import get_provider
    from app.config import get_settings
    from app.models import Member
    from app.services import metrics

    s = get_settings()
    db.configure(s.app_db_path)
    health = get_provider().health()
    if not health.get("ok"):
        print(f"AI not available: {health}", file=sys.stderr)
        return 2
    ap_cases = os.environ.get("AI_EVAL_CASES", "cases.json")
    spec = json.loads((HERE / ap_cases).read_text())
    only = set(filter(None, args.only.split(",")))
    results = []
    with db.session_scope() as session:
        gid = metrics.main_group_id(session)
        members = {k: session.execute(select(Member).filter_by(upstream_id=v)).scalar_one() for k, v in spec["members"].items()}
        truth = {
            "active_members": metrics.member_totals(session, metrics.default_scope(session, 30, gid))["active_members"],
            "unanswered": metrics.support_metrics(session, metrics.default_scope(session, 30, gid))["unanswered_now"],
            "stalled": len(metrics.segment_members(session, "stalled_progress", {"days": 14}, gid)),
            "kavya_lessons": metrics.member_profile(session, session.execute(select(Member).filter_by(upstream_id="syn-mem-scn-silent")).scalar_one().id,
                                                    metrics.default_scope(session, 90, gid))["lessons_marked_complete"],
            "joined_14": metrics.member_totals(session, metrics.default_scope(session, 14, gid))["joined_in_range"],
            # alternative documented definition used by the segment tool (active members, last 14×24 h)
            "pending_onboarding": len(metrics.segment_members(session, "pending_onboarding", {}, gid)),
            "joined_14_segment": len(metrics.segment_members(session, "new_members", {"days": 14}, gid)),
        }
        for case in spec["cases"]:
            if only and case["id"] not in only:
                continue
            t0 = time.monotonic()
            if case["cat"] == "analytics":
                r = chat.ask(session, case["q"])
                answer = r.get("answer") or ""
                tkey = case["truth"]
                if tkey == "joined_14" and r.get("tool") == "segment":
                    tkey = "joined_14_segment"  # truth follows the tool (and definition) actually used
                tv = truth.get(tkey) if tkey else None
                ok_tool = r.get("tool") in case["tool"]
                if case["truth"] is None:
                    passed = ok_tool and "deleted" not in answer.lower() and (r["status"] in ("ok", "unverified_wording"))
                else:
                    passed = ok_tool and r["status"] == "ok" and str(tv) in answer
                results.append({"id": case["id"], "cat": case["cat"], "q": case["q"], "status": r["status"], "tool": r.get("tool"),
                                "truth": tv, "answer": answer, "pass": passed, "seconds": round(time.monotonic() - t0, 1),
                                "detail": r.get("detail")})
            else:
                res = answer_question(session, case["q"], asker=members[case["tier"]], task="ai_eval")
                text = res.text or ""
                cited = {c["doc_key"] for c in res.citations}
                problems = []
                if res.status not in case["expect"]:
                    problems.append(f"status {res.status} not in {case['expect']}")
                for m in case.get("must", []):
                    if m.lower() not in text.lower():
                        problems.append(f"missing '{m}'")
                if case.get("must_any") and not any(m.lower() in text.lower() for m in case["must_any"]):
                    problems.append(f"none of {case['must_any']}")
                for m in case.get("must_not", []):
                    if m.lower() in text.lower():
                        problems.append(f"forbidden '{m}' present")
                if res.status == "answered" and case.get("cite") and not (cited & set(case["cite"])):
                    problems.append(f"cited {sorted(cited)} not in {case['cite']}")
                results.append({"id": case["id"], "cat": case["cat"], "tier": case["tier"], "q": case["q"], "status": res.status,
                                "answer": text, "citations": sorted(cited), "reasons": res.reasons, "auto_publish_ok": res.auto_publish_ok,
                                "pass": not problems, "problems": problems, "seconds": round(time.monotonic() - t0, 1)})
            r0 = results[-1]
            print(f"{r0['id']:4} {'PASS' if r0['pass'] else 'FAIL'} {r0['status']:12} {r0['seconds']:6.1f}s  {'; '.join(r0.get('problems', [])) or ''}", flush=True)
            session.commit()
    by_cat: dict[str, dict[str, int]] = {}
    for r in results:
        c = by_cat.setdefault(r["cat"], {"n": 0, "pass": 0})
        c["n"] += 1
        c["pass"] += int(r["pass"])
    secs = [r["seconds"] for r in results]
    unsafe = [r["id"] for r in results if r["cat"] in ("restricted", "injection", "staff_only") and not r["pass"]]
    auto_wrong = [r["id"] for r in results if r.get("auto_publish_ok") and not r["pass"]]
    summary = {
        "model": s.ollama_model, "model_digest": health.get("digest"), "ollama": health.get("ollama_version"),
        "num_ctx": s.ai_num_ctx, "run_at_utc": datetime.now(UTC).isoformat(), "n": len(results),
        "passed": sum(r["pass"] for r in results), "by_category": by_cat,
        "latency_s": {"median": statistics.median(secs) if secs else None, "max": max(secs) if secs else None},
        "safety_failures": unsafe, "auto_publish_eligible_but_failed": auto_wrong, "truth": truth,
        "hardware_note": "Measured in the build container (x86_64, 4 vCPU, no GPU). Apple M2 Metal performance will differ.",
    }
    out_dir = ROOT / "docs" / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_model = s.ollama_model.replace(":", "_").replace("/", "_")
    suffix = "" if ap_cases == "cases.json" else "-" + Path(ap_cases).stem
    (out_dir / f"ai-eval-{safe_model}{suffix}.json").write_text(json.dumps({"summary": summary, "results": results}, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
