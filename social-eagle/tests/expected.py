"""Independent expected-value calculator working directly on the raw fixture dicts
(not on the database or the metrics module)."""
from __future__ import annotations

from datetime import datetime

from app import fixtures as fx

LEARNER_IDS = set(fx.LEARNERS)


def _in(ts: str, start: datetime, end: datetime) -> bool:
    t = datetime.fromisoformat(ts).astimezone(fx.IST)
    return start <= t < end


def day_bounds(day: str):
    start = datetime.fromisoformat(day + "T00:00:00+05:30")
    return start, start.replace(day=start.day + 1)


def participation(bundles: list[dict], day: str, removed_ids: set[str] = frozenset()) -> dict:
    start, end = day_bounds(day)
    posts = {p["id"]: p for b in bundles for p in b.get("posts", [])}
    comments = {c["id"]: c for b in bundles for c in b.get("comments", [])}
    reactions = {r["id"]: r for b in bundles for r in b.get("reactions", [])}
    authors = {**{k: v["author"] for k, v in posts.items()}, **{k: v["author"] for k, v in comments.items()}}
    out = {"posts": 0, "comments": 0, "likes_given": 0, "likes_received": 0}
    for p in posts.values():
        if p["author"] in LEARNER_IDS and _in(p["created_at"], start, end):
            out["posts"] += 1
    for c in comments.values():
        if c["author"] in LEARNER_IDS and _in(c["created_at"], start, end):
            out["comments"] += 1
    for r in reactions.values():
        if r["id"] in removed_ids or not _in(r["created_at"], start, end):
            continue
        if r["actor"] in LEARNER_IDS:
            out["likes_given"] += 1
        if authors.get(r["target"]) in LEARNER_IDS:
            out["likes_received"] += 1
    return out
