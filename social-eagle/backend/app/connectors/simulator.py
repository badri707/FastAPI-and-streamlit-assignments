"""Stateful local community simulator — the external-community substitute for evaluation mode.

It persists its own state in a separate SQLite file (data/simulator.db), exposes an append-only change
feed with cursors and pagination, accepts new events through evaluation controls, and supports
controlled fault injection. The application never reads simulator tables directly: it goes through
the `CommunityAdapter` contract exactly as a real connector would.

Everything here is SYNTHETIC. Delivery from this adapter never leaves the local machine.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import (
    OPERATIONS,
    AdapterInfo,
    AuthExpired,
    Change,
    ChangePage,
    CommunityAdapter,
    ConnectorUnavailable,
    RateLimited,
    TimeoutUnknownOutcome,
    WriteResult,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sim_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sim_groups (upstream_id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sim_members (
  upstream_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, display_name TEXT NOT NULL, email TEXT,
  role TEXT NOT NULL DEFAULT 'member', tier TEXT, joined_at TEXT, left_at TEXT,
  status TEXT NOT NULL DEFAULT 'active', is_bot INTEGER NOT NULL DEFAULT 0, is_staff INTEGER NOT NULL DEFAULT 0,
  rejoin_count INTEGER NOT NULL DEFAULT 0, onboarding_status TEXT DEFAULT 'unknown', tags TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS sim_posts (
  upstream_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, author_id TEXT, parent_id TEXT, root_id TEXT,
  kind TEXT NOT NULL, title TEXT, body TEXT NOT NULL, category TEXT, created_at TEXT NOT NULL,
  edited_at TEXT, deleted_at TEXT, version INTEGER NOT NULL DEFAULT 1, client_ref TEXT UNIQUE,
  is_automated INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_sim_posts_root ON sim_posts(root_id);
CREATE TABLE IF NOT EXISTS sim_reactions (
  upstream_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, post_id TEXT NOT NULL, member_id TEXT,
  kind TEXT NOT NULL DEFAULT 'like', created_at TEXT NOT NULL, deleted_at TEXT);
CREATE TABLE IF NOT EXISTS sim_courses (
  upstream_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, title TEXT NOT NULL, description TEXT,
  access_tiers TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sim_lessons (
  upstream_id TEXT PRIMARY KEY, course_id TEXT NOT NULL, title TEXT NOT NULL, module TEXT,
  position INTEGER NOT NULL, video_minutes REAL);
CREATE TABLE IF NOT EXISTS sim_progress (
  upstream_id TEXT PRIMARY KEY, member_id TEXT NOT NULL, lesson_id TEXT NOT NULL, kind TEXT NOT NULL,
  occurred_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sim_assignments (
  upstream_id TEXT PRIMARY KEY, course_id TEXT NOT NULL, lesson_id TEXT, title TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sim_submissions (
  upstream_id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL, member_id TEXT NOT NULL, status TEXT NOT NULL,
  submitted_at TEXT NOT NULL, reviewed_at TEXT, reviewer TEXT, feedback TEXT);
CREATE TABLE IF NOT EXISTS sim_events (
  upstream_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, title TEXT NOT NULL, description TEXT,
  starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, cancelled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sim_registrations (
  upstream_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, member_id TEXT NOT NULL, registered_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sim_attendance (
  upstream_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, member_id TEXT NOT NULL, joined_at TEXT,
  left_at TEXT);
CREATE TABLE IF NOT EXISTS sim_leaderboard (
  upstream_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, member_id TEXT NOT NULL, points INTEGER NOT NULL,
  level INTEGER NOT NULL, snapshot_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sim_sessions (
  upstream_id TEXT PRIMARY KEY, member_id TEXT NOT NULL, kind TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sim_messages (
  upstream_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, member_id TEXT NOT NULL, body TEXT NOT NULL,
  sent_at TEXT NOT NULL, client_ref TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS sim_member_actions (
  upstream_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, member_id TEXT NOT NULL, action TEXT NOT NULL,
  params TEXT, at TEXT NOT NULL, client_ref TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS sim_changes (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, entity TEXT NOT NULL, upstream_id TEXT NOT NULL,
  op TEXT NOT NULL, payload TEXT NOT NULL, emitted_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sim_faults (kind TEXT PRIMARY KEY, remaining INTEGER NOT NULL, params TEXT);
CREATE TABLE IF NOT EXISTS sim_write_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, op TEXT NOT NULL, client_ref TEXT,
  outcome TEXT NOT NULL, detail TEXT);
"""

ENTITY_TABLE = {
    "group": "sim_groups",
    "member": "sim_members",
    "post": "sim_posts",
    "reaction": "sim_reactions",
    "course": "sim_courses",
    "lesson": "sim_lessons",
    "progress": "sim_progress",
    "assignment": "sim_assignments",
    "submission": "sim_submissions",
    "event": "sim_events",
    "registration": "sim_registrations",
    "attendance": "sim_attendance",
    "leaderboard": "sim_leaderboard",
    "session": "sim_sessions",
}

FAULT_KINDS = {
    "auth_expired": "Every call fails as an expired login until cleared.",
    "unavailable": "Every call fails as a network/service outage until cleared.",
    "rate_limited": "Calls fail with a rate-limit response.",
    "timeout_after_send": "The next write is persisted remotely but the caller receives a timeout.",
    "timeout_before_send": "The next write times out before anything is persisted.",
    "partial_sync": "The change feed fails after the first page (params.skip_pages, default 1) — a partial sync.",
    "slow": "Each call sleeps `params.seconds` before responding.",
}

SIM_GROUP = "sim-grp-social-eagle"
SIM_GROUP_NAME = "Social Eagle — Evaluation Community (SYNTHETIC)"
OTHER_GROUP = "sim-grp-isolation-check"


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


class SimulatorStore:
    """Direct access to simulator state. Used by the adapter, the seed generator and evaluation controls."""

    def __init__(self, path: Path, clock: Callable[[], datetime]) -> None:
        self.path = path
        self.clock = clock
        self._lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        return c

    # ---- generic mutation with change-feed emission -------------------------------------------
    def upsert(self, c: sqlite3.Connection, entity: str, row: dict[str, Any], emit: bool = True) -> None:
        table = ENTITY_TABLE[entity]
        cols = ", ".join(row.keys())
        ph = ", ".join("?" for _ in row)
        c.execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({ph})", list(row.values()))  # noqa: S608
        if emit:
            self.emit(c, entity, row["upstream_id"], "upsert", row)

    def emit(self, c: sqlite3.Connection, entity: str, upstream_id: str, op: str, payload: dict[str, Any]) -> None:
        c.execute(
            "INSERT INTO sim_changes (entity, upstream_id, op, payload, emitted_at) VALUES (?,?,?,?,?)",
            (entity, upstream_id, op, json.dumps(payload, default=str), _iso(self.clock())),
        )

    def row(self, c: sqlite3.Connection, entity: str, upstream_id: str) -> dict[str, Any] | None:
        r = c.execute(
            f"SELECT * FROM {ENTITY_TABLE[entity]} WHERE upstream_id=?", (upstream_id,)  # noqa: S608
        ).fetchone()
        return dict(r) if r else None

    def next_id(self, c: sqlite3.Connection, prefix: str) -> str:
        r = c.execute("SELECT value FROM sim_meta WHERE key=?", (f"ctr:{prefix}",)).fetchone()
        n = int(r[0]) + 1 if r else 1
        c.execute("INSERT OR REPLACE INTO sim_meta (key, value) VALUES (?, ?)", (f"ctr:{prefix}", str(n)))
        return f"syn-{prefix}-live-{n:05d}"

    def meta(self, key: str) -> str | None:
        with self.connect() as c:
            r = c.execute("SELECT value FROM sim_meta WHERE key=?", (key,)).fetchone()
            return r[0] if r else None

    def set_meta(self, key: str, value: str) -> None:
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO sim_meta (key, value) VALUES (?, ?)", (key, value))

    # ---- faults ---------------------------------------------------------------------------------
    def set_fault(self, kind: str, remaining: int = -1, params: dict[str, Any] | None = None) -> None:
        if kind not in FAULT_KINDS:
            raise ValueError(f"unknown fault {kind}")
        with self.connect() as c:
            c.execute(
                "INSERT OR REPLACE INTO sim_faults (kind, remaining, params) VALUES (?,?,?)",
                (kind, remaining, json.dumps(params or {})),
            )

    def clear_faults(self, kind: str | None = None) -> None:
        with self.connect() as c:
            if kind:
                c.execute("DELETE FROM sim_faults WHERE kind=?", (kind,))
            else:
                c.execute("DELETE FROM sim_faults")

    def faults(self) -> list[dict[str, Any]]:
        with self.connect() as c:
            return [
                {"kind": r["kind"], "remaining": r["remaining"], "params": json.loads(r["params"] or "{}")}
                for r in c.execute("SELECT * FROM sim_faults")
            ]

    def take_fault(self, c: sqlite3.Connection, kind: str) -> dict[str, Any] | None:
        r = c.execute("SELECT remaining, params FROM sim_faults WHERE kind=?", (kind,)).fetchone()
        if not r:
            return None
        if r["remaining"] > 0:
            if r["remaining"] == 1:
                c.execute("DELETE FROM sim_faults WHERE kind=?", (kind,))
            else:
                c.execute("UPDATE sim_faults SET remaining=remaining-1 WHERE kind=?", (kind,))
        return json.loads(r["params"] or "{}")

    def log_write(self, c: sqlite3.Connection, op: str, client_ref: str | None, outcome: str, detail: str = "") -> None:
        c.execute(
            "INSERT INTO sim_write_log (at, op, client_ref, outcome, detail) VALUES (?,?,?,?,?)",
            (_iso(self.clock()), op, client_ref, outcome, detail),
        )

    # ---- evaluation controls (simulate community activity) --------------------------------------
    def add_post(
        self,
        *,
        author_id: str,
        body: str,
        title: str | None = None,
        parent_id: str | None = None,
        category: str | None = "Questions",
        group_id: str = SIM_GROUP,
        at: datetime | None = None,
        client_ref: str | None = None,
        is_automated: bool = False,
    ) -> dict[str, Any]:
        with self._lock, self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                if not self.row(c, "member", author_id):
                    raise ValueError(f"unknown member {author_id}")
                root_id = None
                kind = "post"
                if parent_id:
                    parent = self.row(c, "post", parent_id)
                    if not parent:
                        raise ValueError(f"unknown parent post {parent_id}")
                    root_id = parent["root_id"] or parent["upstream_id"]
                    kind = "comment" if parent["kind"] == "post" else "reply"
                uid = self.next_id(c, "post")
                row = {
                    "upstream_id": uid, "group_id": group_id, "author_id": author_id, "parent_id": parent_id,
                    "root_id": root_id, "kind": kind, "title": title if kind == "post" else None, "body": body,
                    "category": category if kind == "post" else None, "created_at": _iso(at or self.clock()),
                    "edited_at": None, "deleted_at": None, "version": 1, "client_ref": client_ref,
                    "is_automated": 1 if is_automated else 0,
                }
                self.upsert(c, "post", row)
                c.execute("COMMIT")
                return row
            except Exception:
                c.execute("ROLLBACK")
                raise

    def edit_post(self, upstream_id: str, body: str) -> dict[str, Any]:
        with self._lock, self.connect() as c:
            row = self.row(c, "post", upstream_id)
            if not row:
                raise ValueError("unknown post")
            row.update(body=body, edited_at=_iso(self.clock()), version=int(row["version"]) + 1)
            self.upsert(c, "post", row)
            return row

    def delete_post(self, upstream_id: str) -> dict[str, Any]:
        with self._lock, self.connect() as c:
            row = self.row(c, "post", upstream_id)
            if not row:
                raise ValueError("unknown post")
            row.update(deleted_at=_iso(self.clock()))
            self.upsert(c, "post", row)
            return row

    def add_reaction(self, *, post_id: str, member_id: str, kind: str = "like") -> dict[str, Any]:
        with self._lock, self.connect() as c:
            post = self.row(c, "post", post_id)
            if not post or not self.row(c, "member", member_id):
                raise ValueError("unknown post or member")
            row = {
                "upstream_id": self.next_id(c, "rxn"), "group_id": post["group_id"], "post_id": post_id,
                "member_id": member_id, "kind": kind, "created_at": _iso(self.clock()), "deleted_at": None,
            }
            self.upsert(c, "reaction", row)
            return row

    def set_progress(self, *, member_id: str, lesson_id: str, completed: bool = True) -> dict[str, Any]:
        with self._lock, self.connect() as c:
            if not self.row(c, "member", member_id) or not self.row(c, "lesson", lesson_id):
                raise ValueError("unknown member or lesson")
            row = {
                "upstream_id": self.next_id(c, "prog"), "member_id": member_id, "lesson_id": lesson_id,
                "kind": "completed" if completed else "uncompleted", "occurred_at": _iso(self.clock()),
            }
            self.upsert(c, "progress", row)
            return row

    def join_event(self, *, event_id: str, member_id: str, attend: bool = False, minutes: float | None = None) -> dict[str, Any]:
        with self._lock, self.connect() as c:
            ev = self.row(c, "event", event_id)
            if not ev or not self.row(c, "member", member_id):
                raise ValueError("unknown event or member")
            existing = c.execute(
                "SELECT upstream_id FROM sim_registrations WHERE event_id=? AND member_id=?", (event_id, member_id)
            ).fetchone()
            out: dict[str, Any] = {}
            if not existing:
                reg = {
                    "upstream_id": self.next_id(c, "reg"), "event_id": event_id, "member_id": member_id,
                    "registered_at": _iso(self.clock()),
                }
                self.upsert(c, "registration", reg)
                out["registration"] = reg
            if attend:
                joined = datetime.fromisoformat(ev["starts_at"])
                left = None
                if minutes is not None:
                    from datetime import timedelta

                    left = _iso(joined + timedelta(minutes=minutes))
                att = {
                    "upstream_id": self.next_id(c, "att"), "event_id": event_id, "member_id": member_id,
                    "joined_at": _iso(joined), "left_at": left,
                }
                self.upsert(c, "attendance", att)
                out["attendance"] = att
            return out

    def add_member(self, *, display_name: str, tier: str = "general", email: str | None = None) -> dict[str, Any]:
        with self._lock, self.connect() as c:
            uid = self.next_id(c, "mem")
            row = {
                "upstream_id": uid, "group_id": SIM_GROUP, "display_name": display_name,
                "email": email or f"{uid}@example.com", "role": "member", "tier": tier,
                "joined_at": _iso(self.clock()), "left_at": None, "status": "active", "is_bot": 0, "is_staff": 0,
                "rejoin_count": 0, "onboarding_status": "pending", "tags": "[]",
            }
            self.upsert(c, "member", row)
            return row

    def counts(self) -> dict[str, int]:
        with self.connect() as c:
            out = {e: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for e, t in ENTITY_TABLE.items()}  # noqa: S608
            out["changes"] = c.execute("SELECT COUNT(*) FROM sim_changes").fetchone()[0]
            out["messages"] = c.execute("SELECT COUNT(*) FROM sim_messages").fetchone()[0]
            out["member_actions"] = c.execute("SELECT COUNT(*) FROM sim_member_actions").fetchone()[0]
            return out

    def write_log(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT * FROM sim_write_log ORDER BY id DESC LIMIT ?", (limit,))]


class SimulatorAdapter(CommunityAdapter):
    """CommunityAdapter implementation backed by the stateful simulator store."""

    def __init__(self, store: SimulatorStore, page_delay_s: float = 0.0) -> None:
        self.store = store
        self.page_delay_s = page_delay_s
        self.info = AdapterInfo(
            source="simulator",
            mode="evaluation",
            display_name="Local community simulator (synthetic)",
            simulated=True,
            operations={op: True for op in OPERATIONS},
            coverage_notes=[
                "All records are synthetic and generated reproducibly (fixed seed).",
                "Session start/stop events exist only in the simulator to test time-spent calculations.",
                "Supporting an operation here does not imply Skool exposes it.",
            ],
        )

    # Every call passes through the fault gate first.
    def _gate(self, c: sqlite3.Connection, op: str) -> None:
        slow = self.store.take_fault(c, "slow")
        if slow:
            time.sleep(float(slow.get("seconds", 1)))
        if self.store.take_fault(c, "auth_expired") is not None:
            raise AuthExpired("Simulated: session expired — re-authentication required")
        if self.store.take_fault(c, "unavailable") is not None:
            raise ConnectorUnavailable("Simulated: community service unreachable")
        rl = self.store.take_fault(c, "rate_limited")
        if rl is not None:
            raise RateLimited("Simulated: rate limited", float(rl.get("retry_after_s", 30)))

    def health(self) -> dict[str, Any]:
        with self.store.connect() as c:
            try:
                self._gate(c, "health")
            except AuthExpired as e:
                return {"ok": False, "status": "auth_expired", "detail": str(e)}
            except ConnectorUnavailable as e:
                return {"ok": False, "status": "unavailable", "detail": str(e)}
            except RateLimited as e:
                return {"ok": False, "status": "rate_limited", "detail": str(e)}
            head = c.execute("SELECT COALESCE(MAX(seq),0) FROM sim_changes").fetchone()[0]
        return {"ok": True, "status": "ok", "head_cursor": str(head), "simulated": True}

    def fetch_changes(self, cursor: str | None, limit: int = 500) -> ChangePage:
        after = int(cursor or 0)
        with self.store.connect() as c:
            self._gate(c, "fetch")
            pr = c.execute("SELECT params FROM sim_faults WHERE kind='partial_sync'").fetchone()
            if pr is not None:
                params = json.loads(pr["params"] or "{}")
                skip = int(params.get("skip_pages", 1))
                if skip > 0:  # let the first page(s) through, then fail mid-sync
                    params["skip_pages"] = skip - 1
                    c.execute("UPDATE sim_faults SET params=? WHERE kind='partial_sync'", (json.dumps(params),))
                else:
                    self.store.take_fault(c, "partial_sync")
                    raise ConnectorUnavailable("Simulated: change feed failed mid-sync (partial sync)")
            rows = c.execute(
                "SELECT seq, entity, upstream_id, op, payload FROM sim_changes WHERE seq > ? ORDER BY seq LIMIT ?",
                (after, limit + 1),
            ).fetchall()
        if self.page_delay_s:
            time.sleep(self.page_delay_s)
        has_more = len(rows) > limit
        rows = rows[:limit]
        changes = [Change(r["seq"], r["entity"], r["upstream_id"], r["op"], json.loads(r["payload"])) for r in rows]
        nxt = str(changes[-1].seq) if changes else (cursor or "0")
        return ChangePage(changes=changes, next_cursor=nxt, has_more=has_more)

    def list_thread(self, post_upstream_id: str) -> list[dict[str, Any]]:
        with self.store.connect() as c:
            self._gate(c, "list_thread")
            rows = c.execute(
                "SELECT * FROM sim_posts WHERE root_id=? OR upstream_id=? ORDER BY created_at",
                (post_upstream_id, post_upstream_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def _bot_member(self, c: sqlite3.Connection) -> str:
        r = c.execute("SELECT upstream_id FROM sim_members WHERE is_bot=1 ORDER BY upstream_id LIMIT 1").fetchone()
        if not r:
            raise ConnectorUnavailable("Simulator has no assistant account configured")
        return str(r[0])

    def publish_comment(
        self, *, group_upstream_id: str, parent_upstream_id: str, body: str, idempotency_key: str
    ) -> WriteResult:
        with self.store._lock, self.store.connect() as c:
            self._gate(c, "write")
            dup = c.execute("SELECT upstream_id FROM sim_posts WHERE client_ref=?", (idempotency_key,)).fetchone()
            if dup:  # the simulator honours idempotency keys; real platforms may not
                self.store.log_write(c, "comment", idempotency_key, "deduplicated", dup[0])
                return WriteResult(remote_id=dup[0], status="sent", detail={"deduplicated": True})
            if self.store.take_fault(c, "timeout_before_send") is not None:
                self.store.log_write(c, "comment", idempotency_key, "timeout_before_send")
                raise TimeoutUnknownOutcome("Simulated: timed out before send")
            bot = self._bot_member(c)
            fault_after = self.store.take_fault(c, "timeout_after_send")
        row = self.store.add_post(
            author_id=bot, body=body, parent_id=parent_upstream_id, group_id=group_upstream_id,
            client_ref=idempotency_key, is_automated=True,
        )
        with self.store.connect() as c:
            if fault_after is not None:
                self.store.log_write(c, "comment", idempotency_key, "timeout_after_send", row["upstream_id"])
                raise TimeoutUnknownOutcome("Simulated: write persisted but response timed out")
            self.store.log_write(c, "comment", idempotency_key, "sent", row["upstream_id"])
        return WriteResult(remote_id=row["upstream_id"], status="sent", detail={"simulated": True})

    def send_member_message(
        self, *, group_upstream_id: str, member_upstream_id: str, body: str, idempotency_key: str
    ) -> WriteResult:
        with self.store._lock, self.store.connect() as c:
            self._gate(c, "write")
            dup = c.execute("SELECT upstream_id FROM sim_messages WHERE client_ref=?", (idempotency_key,)).fetchone()
            if dup:
                return WriteResult(remote_id=dup[0], status="sent", detail={"deduplicated": True})
            if self.store.take_fault(c, "timeout_before_send") is not None:
                raise TimeoutUnknownOutcome("Simulated: timed out before send")
            uid = self.store.next_id(c, "msg")
            c.execute(
                "INSERT INTO sim_messages (upstream_id, group_id, member_id, body, sent_at, client_ref) VALUES (?,?,?,?,?,?)",
                (uid, group_upstream_id, member_upstream_id, body, _iso(self.store.clock()), idempotency_key),
            )
            fault_after = self.store.take_fault(c, "timeout_after_send")
            self.store.log_write(c, "message", idempotency_key, "timeout_after_send" if fault_after is not None else "sent", uid)
            if fault_after is not None:
                raise TimeoutUnknownOutcome("Simulated: message persisted but response timed out")
        return WriteResult(remote_id=uid, status="sent", detail={"simulated": True})

    def apply_member_action(
        self, *, group_upstream_id: str, member_upstream_id: str, action: str, params: dict[str, Any], idempotency_key: str
    ) -> WriteResult:
        with self.store._lock, self.store.connect() as c:
            self._gate(c, "write")
            dup = c.execute("SELECT upstream_id FROM sim_member_actions WHERE client_ref=?", (idempotency_key,)).fetchone()
            if dup:
                return WriteResult(remote_id=dup[0], status="sent", detail={"deduplicated": True})
            member = self.store.row(c, "member", member_upstream_id)
            if not member:
                raise ConnectorUnavailable("unknown member")
            uid = self.store.next_id(c, "mact")
            c.execute(
                "INSERT INTO sim_member_actions (upstream_id, group_id, member_id, action, params, at, client_ref) VALUES (?,?,?,?,?,?,?)",
                (uid, group_upstream_id, member_upstream_id, action, json.dumps(params), _iso(self.store.clock()), idempotency_key),
            )
            if action in ("ban", "remove"):
                member.update(status="removed", left_at=_iso(self.store.clock()))
                self.store.upsert(c, "member", member)
            self.store.log_write(c, "member_action", idempotency_key, "sent", f"{action}:{uid}")
        return WriteResult(remote_id=uid, status="sent", detail={"simulated": True})

    def find_by_idempotency_key(self, kind: str, idempotency_key: str) -> dict[str, Any] | None:
        table = {"reply": "sim_posts", "message": "sim_messages", "member_action": "sim_member_actions"}.get(kind)
        if table is None:
            return None
        with self.store.connect() as c:
            self._gate(c, "reconcile")
            r = c.execute(f"SELECT * FROM {table} WHERE client_ref=?", (idempotency_key,)).fetchone()  # noqa: S608
        return dict(r) if r else None


def body_signature(body: str) -> str:
    return hashlib.sha256(" ".join(body.split()).encode()).hexdigest()[:16]
