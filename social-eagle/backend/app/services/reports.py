"""Readable summaries and CSV exports. Every export carries scope, date range, sources, last sync and
missing-data notes, and labels synthetic data and simulated delivery. Cells are protected against CSV
formula injection."""
from __future__ import annotations

import csv
import io
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..models import Action, Course, Lesson, LessonCompletion, Member, Post, SupportItem
from ..timeutil import fmt_local, iso, local_date
from . import metrics

DANGEROUS_PREFIX = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(v: Any) -> Any:
    if isinstance(v, str) and v.startswith(DANGEROUS_PREFIX):
        return "'" + v
    return v


def _csv(header_meta: dict[str, Any], columns: list[str], rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    for k, v in header_meta.items():
        w.writerow([safe_cell(f"# {k}"), safe_cell(str(v))])
    w.writerow([])
    w.writerow(columns)
    for r in rows:
        w.writerow([safe_cell(c) for c in r])
    return buf.getvalue()


def _meta(session: Session, scope: metrics.Scope, title: str) -> dict[str, Any]:
    cov = metrics.coverage(session, scope)
    return {
        "report": title, "generated_at": fmt_local(clock.now()), "date_range_ist": f"{scope.start} to {scope.end}",
        "datasets": ",".join(scope.datasets), "source": cov["source"], "last_sync": cov["last_sync"],
        "sync_status": cov["sync_status"], "notes": " | ".join(cov["notes"]) or "none",
        "delivery": "SIMULATED (local simulator) — no external messages were sent",
        "staff_and_bot_activity": "included" if scope.include_staff else "excluded from member activity",
    }


def export(session: Session, kind: str, scope: metrics.Scope) -> tuple[str, str]:
    s, e = scope.utc
    if kind == "members":
        rows = []
        for m in session.execute(select(Member).where(Member.group_id == scope.group_id, Member.is_bot.is_(False),
                                                      Member.dataset.in_(scope.datasets)).order_by(Member.id)).scalars():
            p = metrics.member_profile(session, m.id, scope)
            rows.append([m.upstream_id, m.display_name, m.role, m.tier, m.status, iso(m.joined_at), p["posts"], p["comments"],
                         p["reactions_given"], p["active_contribution_days"], p["last_observed_contribution"] or "unknown",
                         p["lessons_marked_complete"], m.dataset])
        cols = ["upstream_id", "display_name", "role", "tier", "status", "joined_at_utc", "posts", "comments",
                "reactions_given", "active_contribution_days", "last_observed_contribution_utc", "lessons_marked_complete", "dataset"]
    elif kind == "daily":
        c = metrics.contributions(session, scope)
        rows = [[d, v["posts"], v["comments"], v["reactions"], v["contributors"]] for d, v in c["daily"].items()]
        cols = ["date_ist", "posts", "comments", "reactions", "distinct_contributors"]
    elif kind == "support":
        rows = []
        for it, p in session.execute(select(SupportItem, Post).join(Post, Post.id == SupportItem.post_id)
                                     .where(SupportItem.group_id == scope.group_id, Post.created_at >= s, Post.created_at < e)
                                     .order_by(Post.created_at)).all():
            frt = round((it.first_response_at - p.created_at).total_seconds() / 3600, 2) if it.first_response_at else None
            rows.append([p.upstream_id, p.title, it.label, it.label_source, it.status, it.human_verified, iso(p.created_at),
                         iso(it.first_response_at), it.first_response_by, frt, iso(it.resolved_at)])
        cols = ["post_upstream_id", "title", "label", "label_source", "status", "human_verified", "asked_at_utc",
                "first_response_at_utc", "first_response_by", "first_response_hours", "resolved_at_utc"]
    elif kind == "actions":
        rows = [[a.id, a.kind, a.state, a.origin, a.target_upstream_id, a.simulated, a.delivery_target, a.approved_by,
                 iso(a.created_at), a.remote_id, a.error] for a in session.execute(
                     select(Action).where(Action.created_at >= s, Action.created_at < e).order_by(Action.id)).scalars()]
        cols = ["id", "kind", "state", "origin", "target", "simulated", "delivery_target", "approved_by", "created_at_utc",
                "remote_id", "error"]
    elif kind == "progress":
        rows = []
        for c in session.execute(select(Course).where(Course.group_id == scope.group_id)).scalars():
            lessons = session.execute(select(Lesson).where(Lesson.course_id == c.id).order_by(Lesson.position)).scalars().all()
            for lsn in lessons:
                n = session.execute(select(func.count()).where(LessonCompletion.lesson_id == lsn.id,
                                                               LessonCompletion.completed.is_(True))).scalar()
                rows.append([c.title, c.access_tiers, lsn.position, lsn.title, n])
        cols = ["course", "access_tiers_synthetic", "lesson_position", "lesson", "members_marked_complete"]
    else:
        raise ValueError(f"unknown export {kind}")
    return f"social-eagle-{kind}-{scope.start}-{scope.end}.csv", _csv(_meta(session, scope, kind), cols, rows)


def daily_summary(session: Session, day: Any = None) -> dict[str, Any]:
    d = day or (local_date(clock.now()) - timedelta(days=1))
    gid = metrics.main_group_id(session)
    sc = metrics.Scope(group_id=gid, start=d, end=d)
    prev = metrics.Scope(group_id=gid, start=d - timedelta(days=7), end=d - timedelta(days=7))
    c, cp = metrics.contributions(session, sc), metrics.contributions(session, prev)
    sup = metrics.support_metrics(session, sc)
    acts = session.execute(select(Action.state, func.count()).where(Action.created_at >= sc.utc[0], Action.created_at < sc.utc[1])
                           .group_by(Action.state)).all()
    cov = metrics.coverage(session, sc)
    lines = [
        f"Daily summary for {d.isoformat()} (IST) — SYNTHETIC evaluation data",
        f"Posts {c['posts']} (same day last week {cp['posts']}), comments {c['comments']} ({cp['comments']}), "
        f"reactions {c['reactions']} ({cp['reactions']}), distinct contributors {c['distinct_contributors']} ({cp['distinct_contributors']}).",
        f"Questions appearing unanswered now: {sup['unanswered_now']} (aging {sup['unanswered_aging']}).",
        f"Bot/automation actions created that day: {dict(acts) or 'none'} (simulated delivery only).",
        f"Coverage: sync {cov['sync_status']}, last sync {cov['last_sync']}. Notes: {' '.join(cov['notes']) or 'none'}",
    ]
    return {"date": d.isoformat(), "text": "\n".join(lines), "contributions": c, "previous_week_same_day": cp, "support": sup}
