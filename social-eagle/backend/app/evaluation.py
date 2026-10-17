"""seed-evaluation / reset-evaluation.

Refuses to run unless RUN_MODE=evaluation and the target database is the evaluation database inside the
project data directory. Preserves admin accounts; discards all other evaluation state after confirmation.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from . import clock, db
from .config import PROJECT_ROOT, Settings, get_settings
from .connectors.factory import get_adapter, simulator_store
from .migrate import upgrade
from .models import AutomationRule, Segment
from .seed import ANCHOR, DEFAULT_MAIN_MEMBERS, generate, reset_store
from .services import knowledge, sync

BUILTIN_SEGMENTS = [
    ("New members", "new_members", {"days": 14}, "Joined within the last N days."),
    ("No observed contributions", "quiet_members", {"days": 21},
     "Active members with no posts, comments or reactions observed in the last N days. Not the same as inactive: "
     "they may still be reading or learning."),
    ("Pending onboarding", "pending_onboarding", {}, "Onboarding status reported as pending by the source."),
    ("Needs staff attention", "needs_attention", {"hours": 24},
     "Members with an open high-priority support item or a question unanswered for more than N hours."),
    ("Stalled progress", "stalled_progress", {"days": 14},
     "Members with some marked-complete lessons, none in the last N days, and accessible lessons remaining."),
    ("Silent learners", "silent_learners", {"days": 30},
     "Marked lessons complete in the last N days but no observed contributions in that period."),
]


def default_rules(now: Any) -> list[AutomationRule]:
    return [
        AutomationRule(
            name="EVALUATION: auto-reply to answerable FAQ questions", trigger="new_question", action_kind="reply",
            mode="auto", enabled=True, evaluation_only=True, quiet_start="23:00", quiet_end="07:00", max_per_hour=6,
            max_per_day=40, expire_after_minutes=24 * 60,
            conditions={"labels": ["question"], "min_passages": 1, "require_citations": True, "max_question_chars": 1200},
            description="Routine simulated replies so the owner can observe real AI-driven automation before approval. "
                        "Only targets the local simulator. Abstentions, conflicts, restricted-course and support/billing "
                        "items are never auto-published; they go to the review queue.",
            created_at=now, updated_at=now),
        AutomationRule(
            name="Draft replies for questions needing review", trigger="new_question", action_kind="reply", mode="draft",
            enabled=True, evaluation_only=False, max_per_hour=20, max_per_day=100, expire_after_minutes=3 * 24 * 60,
            conditions={"labels": ["question", "needs_support"]},
            description="Prepares drafts for staff review. Nothing is published without approval.",
            created_at=now, updated_at=now),
        AutomationRule(
            name="Stalled learner nudge (draft)", trigger="stalled_progress", action_kind="member_message", mode="draft",
            enabled=True, evaluation_only=False, max_per_hour=10, max_per_day=20, expire_after_minutes=2 * 24 * 60,
            conditions={"days": 14}, description="Drafts a friendly next-lesson suggestion within the member's tier.",
            created_at=now, updated_at=now),
        AutomationRule(
            name="Welcome new members (draft)", trigger="new_member", action_kind="member_message", mode="draft",
            enabled=True, evaluation_only=False, max_per_hour=10, max_per_day=40, expire_after_minutes=2 * 24 * 60,
            conditions={}, description="Drafts a welcome message pointing to the Onboarding Bootcamp.",
            created_at=now, updated_at=now),
        AutomationRule(
            name="Event reminder to registrants (bulk — approval required)", trigger="event_upcoming",
            action_kind="bulk_member_message", mode="draft", enabled=True, evaluation_only=False, max_per_hour=2,
            max_per_day=4, expire_after_minutes=12 * 60, conditions={"hours_before": 24},
            description="Bulk outbound messages always require explicit approval. Reminders expire if the event "
                        "has started (no burst of outdated reminders after sleep).",
            created_at=now, updated_at=now),
    ]


def _guard(settings: Settings) -> None:
    if settings.run_mode != "evaluation":
        raise SystemExit("Refusing: reset-evaluation only runs with RUN_MODE=evaluation")
    target = settings.app_db_path.resolve()
    if target.name != "app.db":
        raise SystemExit(f"Refusing: {target} is not the evaluation database")


def _preserve_users(path: Path) -> list[tuple[Any, ...]]:
    if not path.exists():
        return []
    try:
        con = sqlite3.connect(path)
        rows = con.execute("SELECT username, password_hash, role, created_at FROM users").fetchall()
        con.close()
        return rows
    except sqlite3.Error:
        return []


def reset_evaluation(settings: Settings | None = None, *, run_sync: bool = True,
                     members: int = DEFAULT_MAIN_MEMBERS) -> dict[str, Any]:
    s = settings or get_settings()
    _guard(s)
    users = _preserve_users(s.app_db_path)
    if db._engine is not None:
        db._engine.dispose()
    for p in (s.app_db_path, s.sim_db_path):
        reset_store(p)
    simulator_store.cache_clear()
    db.configure(s.app_db_path)
    upgrade(s.app_db_path)
    clock.invalidate()
    with db.session_scope() as session:
        # "Now" = 10:35 IST on the first day after the 90-day history (outside default quiet hours).
        start_at = ANCHOR + timedelta(hours=10, minutes=35)
        if s.clock_mode == "frozen":
            clock.freeze(session, start_at)
        else:
            clock.align_to(session, start_at)
        for name, rule, params, desc in BUILTIN_SEGMENTS:
            session.add(Segment(name=name, rule=rule, params=params, description=desc, builtin=True))
        for r in default_rules(clock.now()):
            session.add(r)
        if users:
            from .models import User

            for u in users:
                session.add(User(username=u[0], password_hash=u[1], role=u[2], created_at=clock.wall_now()))
    seed_stats = generate(simulator_store(str(s.sim_db_path)), main_members=members)
    with db.session_scope() as session:
        kres = knowledge.ingest_directory(session, PROJECT_ROOT / "seed" / "knowledge")
        emb = knowledge.embed_pending(session)
    out: dict[str, Any] = {"seed": seed_stats, "knowledge": {
        "docs": len(kres), "chunks": sum(r.chunks for r in kres),
        "needs_ocr": [r.doc_key for r in kres if r.status == "needs_ocr"], "embeddings": emb}, "users_preserved": len(users)}
    if run_sync:
        with db.session_scope() as session:
            out["sync"] = sync.sync_once(session, get_adapter("simulator", s))
            out["sync"].pop("new_posts", None)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seed/reset the SYNTHETIC evaluation community")
    ap.add_argument("--yes", action="store_true", help="Confirm discarding current evaluation changes")
    ap.add_argument("--members", type=int, default=DEFAULT_MAIN_MEMBERS, help="Main-group member count (min 250)")
    args = ap.parse_args(argv)
    s = get_settings()
    _guard(s)
    if s.app_db_path.exists() and not args.yes:
        print(f"WARNING: this discards all evaluation changes in {s.data_dir} (app.db and simulator.db).\n"
              "Admin accounts are preserved. Re-run with --yes to confirm.", file=sys.stderr)
        return 2
    import json

    if args.members < 250:
        print("--members must be at least 250 (scenario fixtures need them)", file=sys.stderr)
        return 2
    print(json.dumps(reset_evaluation(s, members=args.members), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
