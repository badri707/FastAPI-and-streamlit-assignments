"""Daily report: build (pure, from the database as of a cutoff), issue (persist
with revisions), render (HTML/CSV/JSON files) and enqueue in-app delivery.

* Re-issuing with identical data returns the existing report (no duplicate).
* Different data for an already-issued date creates a new *revision* that
  supersedes the old one; the old one is kept unchanged.
* Sections whose source is unavailable are reported as unavailable, never as 0.
"""
from __future__ import annotations

import csv
import html
import io
import json
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.analytics import metrics as mx
from app.config import CALC_VERSION, PROJECT_ROOT, Settings
from app.provenance import record_hash
from app.timeutil import fmt_local, iso, local_range_bounds_utc

_env = Environment(loader=FileSystemLoader(PROJECT_ROOT / "app" / "web" / "templates"),
                   autoescape=select_autoescape(["html"]))


def build_report(s: Session, community: m.Community, first: date, last: date, now: datetime,
                 settings: Settings) -> dict:
    start, end = local_range_bounds_utc(first, last)
    cutoff = now
    ctx = mx.Ctx(s, community, start, end, cutoff, settings)
    ctx.load_members()
    health = mx.source_health(ctx)
    avail = mx.section_availability(health)
    configured = [v for v in avail.values() if v != "not_configured"]
    if not configured or all(v == mx.UNAVAILABLE for v in configured):
        status = "unavailable"
    elif all(v == "ok" for v in configured):
        status = "complete"
    else:
        status = "degraded"

    def gated(section: str, fn):
        a = avail[section]
        if a in (mx.UNAVAILABLE,):
            src = mx.SECTION_SOURCES[section]
            return {"availability": a, "reason": f"Source '{src}' did not cover this interval "
                                                 f"(state: {health.get(src, {}).get('state')}). Values withheld — not zero."}
        if a == "not_configured":
            return {"availability": a, "reason": "No source configured for this section in this workspace."}
        return {"availability": a, **fn()}

    status_map = mx.member_status(ctx)
    sections: dict = {}
    sections["membership"] = gated("membership", lambda: mx.membership_summary(ctx, status_map))
    sections["participation"] = gated("participation", lambda: {
        "interval": mx.participation(ctx), "active_days_7": mx.active_days(ctx, 7), "active_days_30": mx.active_days(ctx, 30)})
    sections["learning"] = gated("learning", lambda: mx.learning(ctx))
    sections["assignments"] = gated("assignments", lambda: mx.assignments(ctx))
    sections["wins"] = gated("wins", lambda: mx.wins(ctx))
    sections["support"] = gated("support", lambda: mx.support(ctx))
    sections["leaderboard"] = {"availability": "snapshot_based", **mx.leaderboard(ctx)}
    if all(sections[k]["availability"] in ("ok", "partial") for k in ("learning", "support", "assignments")):
        sections["outreach"] = {"availability": "ok", **mx.outreach_and_followups(
            ctx, status_map, sections["learning"], sections["support"], sections["assignments"], health)}
    else:
        sections["outreach"] = {"availability": mx.UNAVAILABLE,
                                "reason": "Outreach/follow-up lists need learning, support and assignment data; "
                                          "at least one is unavailable for this interval."}

    failed = [{"source": k, **v} for k, v in health.items() if v["state"] != "ok"]
    return {
        "report_type": "daily" if first == last else "range",
        "community": {"slug": community.slug, "name": community.name, "synthetic": community.is_synthetic,
                      "company_community": community.is_company_community},
        "interval": {"first_local_date": first.isoformat(), "last_local_date": last.isoformat(), "timezone": "Asia/Kolkata",
                     "start_utc": iso(start), "end_utc": iso(end), "start_local": fmt_local(start), "end_local": fmt_local(end)},
        "data_cutoff_utc": iso(cutoff),
        "status": status,
        "source_modes": sorted({r.mode for r in s.scalars(select(m.SyncRun).where(m.SyncRun.community_id == community.id))}),
        "data_health": health,
        "section_availability": avail,
        "limitations": failed,
        "calc_version": CALC_VERSION,
        "settings_used": {"support_first_response_target_hours": settings.support_first_response_target_hours,
                          "support_target_basis": settings.support_target_basis,
                          "new_member_grace_days": settings.new_member_grace_days},
        "sections": sections,
    }


def _hashable(payload: dict) -> dict:
    """Content that defines a report. Excludes the cutoff and later-run timestamps in data_health
    so that re-running with unchanged data does not create a spurious revision."""
    keys = ("community", "interval", "status", "section_availability", "sections", "calc_version", "settings_used")
    out = {k: payload[k] for k in keys}
    out["health_states"] = {k: (v["state"], v["known_gaps"]) for k, v in payload["data_health"].items()}
    return out


def issue_report(s: Session, community: m.Community, first: date, last: date, now: datetime, settings: Settings,
                 trigger: str = "manual") -> tuple[m.ReportRun, bool]:
    """Persist a report. Returns (report, created). Identical data → existing report, created=False."""
    payload = build_report(s, community, first, last, now, settings)
    h = record_hash(_hashable(payload))
    prev = s.scalar(select(m.ReportRun).where(m.ReportRun.community_id == community.id,
                                              m.ReportRun.report_date == first.isoformat(),
                                              m.ReportRun.range_end_date == last.isoformat())
                    .order_by(m.ReportRun.revision.desc()))
    if prev is not None and prev.content_hash == h:
        return prev, False
    rev = 1 if prev is None else prev.revision + 1
    reason = None
    if prev is not None:
        reason = _revision_reason(prev.payload, payload)
    start, end = local_range_bounds_utc(first, last)
    rr = m.ReportRun(community_id=community.id, report_date=first.isoformat(), range_end_date=last.isoformat(),
                     revision=rev, supersedes_id=prev.id if prev else None, trigger=trigger, status=payload["status"],
                     generated_at=now, data_cutoff=now, interval_start_utc=start, interval_end_utc=end,
                     calc_version=CALC_VERSION, content_hash=h, payload=payload, revision_reason=reason)
    s.add(rr)
    s.flush()
    rr.output_dir = str(render_files(rr, community, settings))
    enqueue_in_app(s, rr, community, now)
    return rr, True


def _revision_reason(old: dict, new: dict) -> str:
    changes = []
    if old.get("status") != new.get("status"):
        changes.append(f"status {old.get('status')} → {new.get('status')}")
    for k, v in new.get("section_availability", {}).items():
        if old.get("section_availability", {}).get(k) != v:
            changes.append(f"{k} availability {old.get('section_availability', {}).get(k)} → {v}")
    for k in new.get("sections", {}):
        if record_hash(old.get("sections", {}).get(k)) != record_hash(new["sections"][k]):
            changes.append(f"{k} data changed")
    return "Revised after new or late-arriving data: " + ("; ".join(changes) or "content changed")


def enqueue_in_app(s: Session, rr: m.ReportRun, community: m.Community, now: datetime) -> m.OutboxMessage:
    key = f"report:{community.slug}:{rr.report_date}:{rr.range_end_date}:r{rr.revision}:in_app"
    existing = s.scalar(select(m.OutboxMessage).where(m.OutboxMessage.dedupe_key == key))
    if existing:
        return existing
    msg = m.OutboxMessage(dedupe_key=key, channel="in_app", recipient="dashboard", report_run_id=rr.id,
                          subject=f"{community.name}: daily report {rr.report_date} r{rr.revision} ({rr.status})",
                          created_at=now)
    s.add(msg)
    s.flush()
    return msg


# ---------------------------------------------------------------- rendering

_FORMULA_PREFIX = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(v) -> str:
    """Neutralise spreadsheet formula injection."""
    if v is None:
        return ""
    sv = str(v)
    if sv.startswith(_FORMULA_PREFIX):
        return "'" + sv
    return sv


def summary_rows(payload: dict) -> list[tuple[str, str, object]]:
    rows: list[tuple[str, str, object]] = [("report", "status", payload["status"]),
                                           ("report", "interval_start_utc", payload["interval"]["start_utc"]),
                                           ("report", "interval_end_utc", payload["interval"]["end_utc"]),
                                           ("report", "data_cutoff_utc", payload["data_cutoff_utc"]),
                                           ("report", "calc_version", payload["calc_version"])]
    sec = payload["sections"]
    for name, sd in sec.items():
        rows.append((name, "availability", sd["availability"]))
    if sec["membership"]["availability"] in ("ok", "partial"):
        mem = sec["membership"]
        rows.append(("membership", "learners_known", mem["learners_known"]))
        for k, v in mem["by_batch_status"].items():
            rows.append(("membership", f"batch_status:{k}", v))
        for k, v in mem["by_plan_label"].items():
            rows.append(("membership", f"plan:{k}", v))
    if sec["participation"]["availability"] in ("ok", "partial"):
        for k, v in sec["participation"]["interval"]["totals_learners"].items():
            rows.append(("participation", k, v))
        rows.append(("participation", "active_members_7d", sec["participation"]["active_days_7"]["members_with_observed_activity"]))
        rows.append(("participation", "active_members_30d", sec["participation"]["active_days_30"]["members_with_observed_activity"]))
    if sec["learning"]["availability"] in ("ok", "partial"):
        lr = sec["learning"]
        rows += [("learning", "enrolments_counted", lr["enrolments_counted"]),
                 ("learning", "progress_recorded", lr["progress_recorded"]),
                 ("learning", "progress_unknown", lr["progress_unknown"]),
                 ("learning", "overdue_lessons", sum(1 for d in lr["deadline_checks"] if d["status"] == "overdue"))]
    if sec["assignments"]["availability"] in ("ok", "partial"):
        a = sec["assignments"]
        rows += [("assignments", "submitted_in_interval", len(a["submitted_in_interval"])),
                 ("assignments", "feedback_delivered_in_interval", len(a["feedback_delivered_in_interval"])),
                 ("assignments", "awaiting_review", len(a["awaiting_review"]))]
    if sec["wins"]["availability"] in ("ok", "partial"):
        rows.append(("wins", "recorded_in_interval", len(sec["wins"]["wins"])))
    if sec["support"]["availability"] in ("ok", "partial"):
        sp = sec["support"]
        rows += [("support", "new_questions", sp["new_count"]), ("support", "unresolved", len(sp["unresolved"])),
                 ("support", "unresolved_awaiting_staff", sp["unresolved_awaiting_staff"]),
                 ("support", "open_target_breaches", len(sp["target_breaches_open"]))]
    return rows


def render_csv(payload: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "metric", "value"])
    for r in summary_rows(payload):
        w.writerow([csv_safe(x) for x in r])
    return buf.getvalue()


def render_followups_csv(payload: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["type", "member", "source_member_id", "owner", "reason", "source_ref"])
    o = payload["sections"].get("outreach", {})
    for f in o.get("staff_follow_ups", []):
        w.writerow([csv_safe(x) for x in ("staff_follow_up", (f["member"] or {}).get("name"),
                                          (f["member"] or {}).get("source_member_id"), (f["owner"] or {}).get("name"),
                                          f["reason"], f["source_ref"])])
    for c in o.get("outreach_candidates", []):
        for r in c["reasons"]:
            w.writerow([csv_safe(x) for x in ("outreach_candidate", c["member"]["name"], c["member"]["source_member_id"],
                                              "", r, "")])
    return buf.getvalue()


def render_html(payload: dict, rr: m.ReportRun | None = None) -> str:
    return _env.get_template("report.html").render(p=payload, rr=rr, fmt_local=fmt_local, json=json, html=html)


def render_files(rr: m.ReportRun, community: m.Community, settings: Settings) -> Path:
    out = settings.reports_dir / community.slug / f"{rr.report_date}_{rr.range_end_date}" / f"r{rr.revision}"
    out.mkdir(parents=True, exist_ok=True)
    meta = {"report_run_id": rr.id, "revision": rr.revision, "supersedes_id": rr.supersedes_id, "trigger": rr.trigger,
            "generated_at_utc": iso(rr.generated_at), "content_hash": rr.content_hash, "revision_reason": rr.revision_reason}
    (out / "report.json").write_text(json.dumps({"meta": meta, **rr.payload}, indent=2, default=str), encoding="utf-8")
    (out / "summary.csv").write_text(render_csv(rr.payload), encoding="utf-8")
    (out / "follow_ups.csv").write_text(render_followups_csv(rr.payload), encoding="utf-8")
    (out / "report.html").write_text(render_html(rr.payload, rr), encoding="utf-8")
    return out
