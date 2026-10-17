"""Deterministic metrics. Every number shown in reports, dashboards and owner chat comes from here.

Definitions (also in docs/METRICS.md and returned by /api/metrics/definitions):
- Dates are Asia/Kolkata calendar days; ranges are inclusive of both end dates and converted to half-open UTC.
- Contribution = a post, comment/reply or reaction created by the member in the group (not deleted).
- Member activity excludes staff and the bot unless include_staff / include_bot is set; staff and bot activity
  is always reported separately.
- Active contribution day = a distinct (member, IST date) with at least one contribution. This is NOT time online.
- Appears unanswered = support item in open/assigned/drafted with no reply from anyone other than the asker.
- First response time = first reply by someone other than the asker minus question time.
- Resolution time = human-marked resolution minus question time (only human-verified resolutions count).
- Lesson completion = marked complete at the source. It does not prove the video was watched or understood.
- Missing observations are reported as unknown, never as zero.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from .. import clock
from ..models import (
    Course,
    Event,
    EventAttendance,
    EventRegistration,
    Group,
    LeaderboardSnapshot,
    Lesson,
    LessonCompletion,
    Member,
    Post,
    ProgressEvent,
    Reaction,
    SessionEvent,
    SupportItem,
    SyncState,
)
from ..timeutil import IST, iso, local_date, local_range_utc

DEFINITIONS = {k.strip(): v.strip() for k, v in (line.split("=", 1) for line in __doc__.split("\n- ")[1:] if "=" in line)}
SESSION_IDLE_CAP_MIN = 30


@dataclass
class Scope:
    group_id: int
    start: date
    end: date
    datasets: list[str] = field(default_factory=lambda: ["synthetic"])
    include_staff: bool = False
    include_bot: bool = False

    @property
    def utc(self) -> tuple[datetime, datetime]:
        return local_range_utc(self.start, self.end, IST)

    def describe(self) -> dict[str, Any]:
        s, e = self.utc
        return {"group_id": self.group_id, "start_ist": self.start.isoformat(), "end_ist": self.end.isoformat(),
                "utc_start": iso(s), "utc_end_exclusive": iso(e), "datasets": self.datasets,
                "include_staff": self.include_staff, "include_bot": self.include_bot, "timezone": "Asia/Kolkata"}


def default_scope(session: Session, days: int = 30, group_id: int | None = None) -> Scope:
    today = local_date(clock.now())
    gid = group_id or main_group_id(session)
    return Scope(group_id=gid, start=today - timedelta(days=days - 1), end=today)


def main_group_id(session: Session) -> int:
    """The default group: the non-import group with the most members (imports never become the default)."""
    row = session.execute(select(Group.id, func.count(Member.id).label("n")).outerjoin(Member, Member.group_id == Group.id)
                          .where(Group.source != "import").group_by(Group.id).order_by(func.count(Member.id).desc(), Group.id)).first()
    if row is None:
        raise LookupError("No community data synced yet")
    return int(row[0])


def _member_filter(scope: Scope) -> list[Any]:
    conds: list[Any] = [Member.group_id == scope.group_id, Member.dataset.in_(scope.datasets)]
    if not scope.include_staff:
        conds.append(Member.is_staff.is_(False))
    if not scope.include_bot:
        conds.append(Member.is_bot.is_(False))
    return conds


def coverage(session: Session, scope: Scope) -> dict[str, Any]:
    st = session.execute(select(SyncState).order_by(SyncState.id)).scalars().first()
    first_obs = session.execute(
        select(func.min(Post.created_at)).where(Post.group_id == scope.group_id, Post.dataset.in_(scope.datasets))
    ).scalar()
    today = local_date(clock.now())
    notes = []
    if scope.end >= today:
        notes.append(f"{today.isoformat()} (today, IST) is incomplete.")
    if first_obs and scope.utc[0] < first_obs:
        notes.append(f"No observations before {local_date(first_obs).isoformat()}; earlier days are unknown, not zero.")
    if st is None or st.status != "ok":
        notes.append(f"Last sync status: {st.status if st else 'never'} — figures may be stale or partial.")
    if "synthetic" in scope.datasets:
        notes.append("Includes SYNTHETIC evaluation data.")
    return {
        "source": st.source if st else None, "sync_status": st.status if st else "never",
        "last_sync": iso(st.last_success_at) if st else None, "complete": bool(st and (st.coverage or {}).get("complete")),
        "observations_start": iso(first_obs), "notes": notes,
    }


def contributions(session: Session, scope: Scope) -> dict[str, Any]:
    s, e = scope.utc
    mf = _member_filter(scope)
    posts_q = (select(Post.author_id, Post.kind, Post.created_at).join(Member, Member.id == Post.author_id)
               .where(*mf, Post.group_id == scope.group_id, Post.created_at >= s, Post.created_at < e,
                      Post.deleted_at.is_(None), Post.dataset.in_(scope.datasets)))
    rx_q = (select(Reaction.member_id, Reaction.created_at).join(Member, Member.id == Reaction.member_id)
            .where(*mf, Reaction.group_id == scope.group_id, Reaction.created_at >= s, Reaction.created_at < e,
                   Reaction.deleted_at.is_(None), Reaction.dataset.in_(scope.datasets)))
    posts = session.execute(posts_q).all()
    rxs = session.execute(rx_q).all()
    n_posts = sum(1 for p in posts if p.kind == "post")
    n_comments = sum(1 for p in posts if p.kind in ("comment", "reply"))
    days: set[tuple[int, date]] = set()
    daily: dict[str, dict[str, int]] = {}
    d = scope.start
    while d <= scope.end:
        daily[d.isoformat()] = {"posts": 0, "comments": 0, "reactions": 0, "contributors": 0}
        d += timedelta(days=1)
    contributors_by_day: dict[str, set[int]] = {k: set() for k in daily}
    for p in posts:
        ld = local_date(p.created_at).isoformat()
        daily[ld]["posts" if p.kind == "post" else "comments"] += 1
        days.add((p.author_id, local_date(p.created_at)))
        contributors_by_day[ld].add(p.author_id)
    for r in rxs:
        ld = local_date(r.created_at).isoformat()
        daily[ld]["reactions"] += 1
        days.add((r.member_id, local_date(r.created_at)))
        contributors_by_day[ld].add(r.member_id)
    for k, v in contributors_by_day.items():
        daily[k]["contributors"] = len(v)
    contributors = {p.author_id for p in posts} | {r.member_id for r in rxs}
    # Staff and bot reported separately, always.
    staff_bot = session.execute(
        select(Member.is_bot, func.count(Post.id)).join(Member, Member.id == Post.author_id)
        .where(Post.group_id == scope.group_id, Post.created_at >= s, Post.created_at < e, Post.deleted_at.is_(None),
               Post.dataset.in_(scope.datasets), or_(Member.is_staff.is_(True), Member.is_bot.is_(True)))
        .group_by(Member.is_bot)
    ).all()
    sb = {"staff_posts_and_comments": 0, "bot_posts_and_comments": 0}
    for is_bot, n in staff_bot:
        sb["bot_posts_and_comments" if is_bot else "staff_posts_and_comments"] = n
    return {"posts": n_posts, "comments": n_comments, "reactions": len(rxs), "distinct_contributors": len(contributors),
            "active_contribution_days": len(days), "daily": daily, "separate": sb}


def member_totals(session: Session, scope: Scope) -> dict[str, Any]:
    s, e = scope.utc
    base = [Member.group_id == scope.group_id, Member.dataset.in_(scope.datasets), Member.is_bot.is_(False)]
    rows = session.execute(select(Member.status, Member.tier, Member.is_staff, func.count()).where(*base)
                           .group_by(Member.status, Member.tier, Member.is_staff)).all()
    active = sum(n for st, _t, staff, n in rows if st == "active" and not staff)
    by_tier: dict[str, int] = {}
    for st, t, staff, n in rows:
        if st == "active" and not staff:
            by_tier[t or "unknown"] = by_tier.get(t or "unknown", 0) + n
    joined = session.execute(select(func.count()).where(*base, Member.is_staff.is_(False), Member.joined_at >= s,
                                                         Member.joined_at < e)).scalar()
    left = session.execute(select(func.count()).where(*base, Member.is_staff.is_(False), Member.left_at >= s,
                                                       Member.left_at < e)).scalar()
    staff_count = sum(int(n) for st, _t, is_staff, n in rows if is_staff and st == "active")
    return {"active_members": active, "staff": staff_count, "by_tier": by_tier, "joined_in_range": joined, "left_in_range": left,
            "left_total": sum(n for st, _t, staff_, n in rows if st in ("left", "removed") and not staff_)}


def _hours(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 3600


def support_metrics(session: Session, scope: Scope) -> dict[str, Any]:
    s, e = scope.utc
    now = clock.now()
    items = session.execute(
        select(SupportItem, Post.created_at).join(Post, Post.id == SupportItem.post_id)
        .where(SupportItem.group_id == scope.group_id, Post.dataset.in_(scope.datasets))
    ).all()
    unanswered = [(i, c) for i, c in items if i.status in ("open", "assigned", "drafted") and i.first_response_at is None]
    buckets = {"<24h": 0, "1-3d": 0, "3-7d": 0, ">7d": 0}
    for _i, c in unanswered:
        h = _hours(c, now)
        buckets["<24h" if h < 24 else "1-3d" if h < 72 else "3-7d" if h < 168 else ">7d"] += 1
    in_range = [(i, c) for i, c in items if s <= c < e]
    frt = [_hours(c, i.first_response_at) for i, c in in_range if i.first_response_at]
    frt_by: dict[str, list[float]] = {}
    for i, c in in_range:
        if i.first_response_at:
            frt_by.setdefault(i.first_response_by or "unknown", []).append(_hours(c, i.first_response_at))
    res = [_hours(c, i.resolved_at) for i, c in in_range if i.resolved_at and i.human_verified]

    def summ(v: list[float]) -> dict[str, Any]:
        if not v:
            return {"n": 0, "median_hours": None, "p90_hours": None}
        v = sorted(v)
        return {"n": len(v), "median_hours": round(statistics.median(v), 2),
                "p90_hours": round(v[min(len(v) - 1, int(0.9 * len(v)))], 2)}

    return {
        "unanswered_now": len(unanswered), "unanswered_aging": buckets,
        "questions_in_range": len(in_range), "answered_in_range": len(frt),
        "first_response": summ(frt), "first_response_by": {k: summ(v) for k, v in frt_by.items()},
        "human_verified_resolution": summ(res),
        "open_by_label": _count_by(session, scope),
        "definitions": {"unanswered": DEFINITIONS.get("Appears unanswered"), "first_response": DEFINITIONS.get("First response time")},
    }


def _count_by(session: Session, scope: Scope) -> dict[str, int]:
    rows = session.execute(select(SupportItem.label, func.count()).where(
        SupportItem.group_id == scope.group_id, SupportItem.status.in_(["open", "assigned", "drafted"])
    ).group_by(SupportItem.label)).all()
    return {lbl: n for lbl, n in rows}


def learning(session: Session, scope: Scope) -> dict[str, Any]:
    s, e = scope.utc
    mf = _member_filter(scope)
    ev = session.execute(
        select(ProgressEvent.kind, func.count(), func.count(func.distinct(ProgressEvent.member_id)))
        .join(Member, Member.id == ProgressEvent.member_id)
        .where(*mf, ProgressEvent.occurred_at >= s, ProgressEvent.occurred_at < e, ProgressEvent.dataset.in_(scope.datasets))
        .group_by(ProgressEvent.kind)
    ).all()
    out_ev = {k: {"events": n, "members": m} for k, n, m in ev}
    courses = []
    for c in session.execute(select(Course).where(Course.group_id == scope.group_id)).scalars():
        lessons = session.execute(select(Lesson.id).where(Lesson.course_id == c.id)).scalars().all()
        eligible = session.execute(select(func.count()).where(*mf, Member.status == "active",
                                                               Member.tier.in_(c.tiers()))).scalar() or 0
        per_member = session.execute(
            select(LessonCompletion.member_id, func.count()).join(Member, Member.id == LessonCompletion.member_id)
            .where(*mf, Member.status == "active", LessonCompletion.lesson_id.in_(lessons), LessonCompletion.completed.is_(True))
            .group_by(LessonCompletion.member_id)
        ).all()
        finished = sum(1 for _m, n in per_member if n >= len(lessons))
        started = len(per_member)
        courses.append({"course_id": c.id, "upstream_id": c.upstream_id, "title": c.title, "access_tiers": c.access_tiers,
                        "policy_label": c.policy_label, "lessons": len(lessons), "eligible_active_members": eligible,
                        "started": started, "finished_all_marked_complete": finished,
                        "finish_rate_of_eligible": round(finished / eligible, 4) if eligible else None})
    return {"progress_events_in_range": out_ev, "courses": courses,
            "note": "Marked complete ≠ watched the full video or understood the material."}


def events_metrics(session: Session, scope: Scope) -> dict[str, Any]:
    s, e = scope.utc
    out = []
    for ev in session.execute(select(Event).where(Event.group_id == scope.group_id, Event.starts_at >= s,
                                                  Event.starts_at < e).order_by(Event.starts_at)).scalars():
        regs = session.execute(select(func.count()).where(EventRegistration.event_id == ev.id)).scalar() or 0
        att = session.execute(select(EventAttendance).where(EventAttendance.event_id == ev.id)).scalars().all()
        known = [a.duration_minutes for a in att if a.duration_minutes is not None]
        reg_ids = set(session.execute(select(EventRegistration.member_id).where(EventRegistration.event_id == ev.id)).scalars())
        out.append({"event_id": ev.id, "title": ev.title, "starts_at": iso(ev.starts_at), "registered": regs,
                    "attended": len(att), "attended_registered": sum(1 for a in att if a.member_id in reg_ids),
                    "walk_ins": sum(1 for a in att if a.member_id not in reg_ids),
                    "attendance_rate_of_registered": round(sum(1 for a in att if a.member_id in reg_ids) / regs, 3) if regs else None,
                    "duration_known": len(known), "duration_unknown": len(att) - len(known),
                    "avg_known_duration_min": round(sum(known) / len(known), 1) if known else None,
                    "upcoming": ev.starts_at > clock.now()})
    return {"events": out, "note": "Registration, attendance and attendance duration are tracked separately; unknown durations are not zero."}


def leaderboard(session: Session, scope: Scope, top: int = 10) -> dict[str, Any]:
    snaps = session.execute(select(LeaderboardSnapshot.snapshot_at).where(LeaderboardSnapshot.group_id == scope.group_id)
                            .distinct().order_by(LeaderboardSnapshot.snapshot_at.desc()).limit(2)).scalars().all()
    if not snaps:
        return {"latest": None, "rows": [], "note": "No leaderboard snapshots observed."}
    latest, prev = snaps[0], (snaps[1] if len(snaps) > 1 else None)
    prev_pts = dict(session.execute(select(LeaderboardSnapshot.member_id, LeaderboardSnapshot.points)
                                    .where(LeaderboardSnapshot.snapshot_at == prev)).all()) if prev else {}
    rows = session.execute(select(LeaderboardSnapshot, Member).join(Member, Member.id == LeaderboardSnapshot.member_id)
                           .where(LeaderboardSnapshot.snapshot_at == latest, LeaderboardSnapshot.group_id == scope.group_id)
                           .order_by(LeaderboardSnapshot.points.desc(), Member.id).limit(top)).all()
    return {"latest": iso(latest), "previous": iso(prev), "rows": [
        {"member_id": m.id, "name": m.display_name, "points": lb.points, "level": lb.level,
         "change": (lb.points - prev_pts[m.id]) if m.id in prev_pts else None} for lb, m in rows],
        "note": "SYNTHETIC points modelled on the public description (likes received). Not Skool's official score; "
                "points do not measure learning or helpfulness."}


def time_spent(session: Session, member_id: int, start: datetime, end: datetime) -> dict[str, Any]:
    """Time-spent from explicitly SYNTHETIC session events. Rules: concurrent sessions (e.g. two devices) are allowed;
    a stop closes the earliest open start; a start with no stop within SESSION_IDLE_CAP_MIN minutes is capped at that
    cap; a stop without an open start is ignored; overlapping intervals are merged so time is never double-counted."""
    evs = session.execute(select(SessionEvent).where(SessionEvent.member_id == member_id, SessionEvent.at >= start,
                                                     SessionEvent.at < end).order_by(SessionEvent.at, SessionEvent.id)).scalars().all()
    if not evs:
        return {"status": "unavailable", "minutes": None,
                "note": "No session events observed for this member/period. Time spent is unknown — not zero."}
    cap = timedelta(minutes=SESSION_IDLE_CAP_MIN)
    intervals: list[tuple[datetime, datetime]] = []
    open_starts: list[datetime] = []
    capped = 0
    for ev in evs:
        for st in [s for s in open_starts if s + cap < ev.at]:  # stale: idle longer than the cap
            open_starts.remove(st)
            intervals.append((st, st + cap))
            capped += 1
        if ev.kind == "start":
            open_starts.append(ev.at)
        elif ev.kind == "stop" and open_starts:
            intervals.append((open_starts.pop(0), ev.at))
    for st in open_starts:
        intervals.append((st, min(end, st + cap)))
        capped += 1
    intervals.sort()
    merged: list[list[datetime]] = []
    for a, b in intervals:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    minutes = sum((b - a).total_seconds() for a, b in merged) / 60
    return {"status": "synthetic", "minutes": round(minutes, 1), "sessions": len(merged), "capped_sessions": capped,
            "note": "Calculated from SYNTHETIC session events. Elapsed time does not prove attention."}


def member_profile(session: Session, member_id: int, scope: Scope) -> dict[str, Any]:
    s, e = scope.utc
    m = session.get(Member, member_id)
    if m is None:
        raise LookupError("member not found")
    posts = session.execute(select(Post.kind, func.count()).where(Post.author_id == member_id, Post.deleted_at.is_(None),
                                                                  Post.created_at >= s, Post.created_at < e)
                            .group_by(Post.kind)).all()
    pc = dict(posts)
    rx_given = session.execute(select(func.count()).where(Reaction.member_id == member_id, Reaction.created_at >= s,
                                                          Reaction.created_at < e)).scalar()
    rx_recv = session.execute(select(func.count()).select_from(Reaction).join(Post, Post.id == Reaction.post_id)
                              .where(Post.author_id == member_id, Reaction.created_at >= s, Reaction.created_at < e,
                                     Reaction.member_id != member_id)).scalar()
    last_contrib = max(filter(None, [
        session.execute(select(func.max(Post.created_at)).where(Post.author_id == member_id)).scalar(),
        session.execute(select(func.max(Reaction.created_at)).where(Reaction.member_id == member_id)).scalar(),
    ]), default=None)
    days = list(session.execute(select(Post.created_at).where(Post.author_id == member_id, Post.created_at >= s,
                                                              Post.created_at < e)).scalars().all())
    days += session.execute(select(Reaction.created_at).where(Reaction.member_id == member_id, Reaction.created_at >= s,
                                                              Reaction.created_at < e)).scalars().all()
    accessible = session.execute(select(func.count(Lesson.id)).join(Course, Course.id == Lesson.course_id)
                                 .where(Course.group_id == m.group_id, Course.access_tiers.contains(m.tier or "__none__"))).scalar()
    completed = session.execute(select(func.count()).where(LessonCompletion.member_id == member_id,
                                                           LessonCompletion.completed.is_(True))).scalar()
    last_prog = session.execute(select(func.max(ProgressEvent.occurred_at)).where(ProgressEvent.member_id == member_id)).scalar()
    attended = session.execute(select(func.count()).where(EventAttendance.member_id == member_id)).scalar()
    return {
        "posts": pc.get("post", 0), "comments": pc.get("comment", 0) + pc.get("reply", 0), "reactions_given": rx_given,
        "reactions_received": rx_recv, "active_contribution_days": len({local_date(d) for d in days}),
        "last_observed_contribution": iso(last_contrib), "lessons_marked_complete": completed,
        "accessible_lessons": accessible, "last_progress_event": iso(last_prog), "events_attended": attended,
        "time_spent": time_spent(session, member_id, s, e),
    }


def overview(session: Session, scope: Scope) -> dict[str, Any]:
    from ..models import Action, Job

    pending = session.execute(select(func.count()).where(Action.state.in_(["drafted", "approved", "queued", "held", "unknown_outcome"]))).scalar()
    queued = session.execute(select(func.count()).where(Job.status.in_(["queued", "leased"]))).scalar()
    return {"scope": scope.describe(), "members": member_totals(session, scope), "contributions": contributions(session, scope),
            "support": support_metrics(session, scope), "pending_actions": pending, "queued_jobs": queued,
            "coverage": coverage(session, scope)}


def compare(session: Session, a: Scope, b: Scope) -> dict[str, Any]:
    ca, cb = contributions(session, a), contributions(session, b)
    keys = ["posts", "comments", "reactions", "distinct_contributors", "active_contribution_days"]
    return {"a": a.describe(), "b": b.describe(),
            "rows": [{"metric": k, "a": ca[k], "b": cb[k], "delta": cb[k] - ca[k],
                      "pct_change": round((cb[k] - ca[k]) / ca[k] * 100, 1) if ca[k] else None} for k in keys]}


def segment_members(session: Session, rule: str, params: dict[str, Any], group_id: int) -> list[int]:
    now = clock.now()
    base = [Member.group_id == group_id, Member.status == "active", Member.is_bot.is_(False), Member.is_staff.is_(False)]
    if rule == "new_members":
        since = now - timedelta(days=int(params.get("days", 14)))
        return list(session.execute(select(Member.id).where(*base, Member.joined_at >= since)).scalars())
    if rule == "pending_onboarding":
        return list(session.execute(select(Member.id).where(*base, Member.onboarding_status == "pending")).scalars())
    if rule in ("quiet_members", "silent_learners"):
        days = int(params.get("days", 21))
        since = now - timedelta(days=days)
        posted = select(Post.author_id).where(Post.created_at >= since, Post.author_id.is_not(None))
        reacted = select(Reaction.member_id).where(Reaction.created_at >= since, Reaction.member_id.is_not(None))
        q = select(Member.id).where(*base, Member.id.not_in(posted), Member.id.not_in(reacted))
        if rule == "quiet_members":
            q = q.where(Member.joined_at < since)
        else:
            q = q.where(Member.id.in_(select(ProgressEvent.member_id).where(ProgressEvent.occurred_at >= since)))
        return list(session.execute(q).scalars())
    if rule == "needs_attention":
        hours = int(params.get("hours", 24))
        cutoff = now - timedelta(hours=hours)
        attn = (select(Post.author_id).join(SupportItem, SupportItem.post_id == Post.id)
             .where(SupportItem.status.in_(["open", "assigned", "drafted"]),
                    or_(and_(SupportItem.priority == "high"), and_(SupportItem.first_response_at.is_(None), Post.created_at < cutoff))))
        return list(session.execute(select(Member.id).where(*base, Member.id.in_(attn))).scalars())
    if rule == "stalled_progress":
        days = int(params.get("days", 14))
        cutoff = now - timedelta(days=days)
        last = (select(ProgressEvent.member_id, func.max(ProgressEvent.occurred_at).label("last"))
                .group_by(ProgressEvent.member_id).subquery())
        rows = session.execute(select(Member.id, Member.tier).join(last, last.c.member_id == Member.id)
                               .where(*base, last.c.last < cutoff)).all()
        out = []
        for mid, tier in rows:
            acc = session.execute(select(func.count(Lesson.id)).join(Course, Course.id == Lesson.course_id)
                                  .where(Course.group_id == group_id, Course.access_tiers.contains(tier or "__none__"))).scalar() or 0
            done = session.execute(select(func.count()).where(LessonCompletion.member_id == mid, LessonCompletion.completed.is_(True))).scalar() or 0
            if 0 < done < acc:
                out.append(mid)
        return out
    raise ValueError(f"unknown segment rule {rule}")


def next_lesson(session: Session, member_id: int) -> dict[str, Any] | None:
    """Suggest the first not-completed lesson in courses the member's tier can access (course order, then position)."""
    m = session.get(Member, member_id)
    if m is None:
        return None
    done = set(session.execute(select(LessonCompletion.lesson_id).where(LessonCompletion.member_id == member_id,
                                                                         LessonCompletion.completed.is_(True))).scalars())
    for c in session.execute(select(Course).where(Course.group_id == m.group_id).order_by(Course.id)).scalars():
        if (m.tier or "") not in c.tiers():
            continue
        lessons = session.execute(select(Lesson).where(Lesson.course_id == c.id).order_by(Lesson.position)).scalars().all()
        started = any(lsn.id in done for lsn in lessons)
        for lsn in lessons:
            if lsn.id not in done and (started or c.id == lessons[0].course_id):
                return {"course": c.title, "course_upstream_id": c.upstream_id, "lesson": lsn.title,
                        "lesson_upstream_id": lsn.upstream_id, "position": lsn.position}
    return None
