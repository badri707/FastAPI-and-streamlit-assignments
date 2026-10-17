"""Seeded synthetic community: reconciliation with source records, named scenarios, failure handling."""
from __future__ import annotations

import sqlite3

from sqlalchemy import func, select

from app import db
from app.config import get_settings
from app.connectors.factory import get_adapter, get_store
from app.models import Member, Post, Reaction, SupportItem, SyncState
from app.services import metrics, sync


def sim_count(sql: str) -> int:
    con = sqlite3.connect(get_settings().sim_db_path)
    n = con.execute(sql).fetchone()[0]
    con.close()
    return n


def test_seed_reconciles_with_source_records(seeded):
    with db.session_scope() as s:
        assert s.query(Member).count() == sim_count("SELECT COUNT(*) FROM sim_members")
        assert s.query(Post).count() == sim_count("SELECT COUNT(*) FROM sim_posts")
        assert s.query(Reaction).count() == sim_count("SELECT COUNT(*) FROM sim_reactions")
        # duplicates in the feed did not inflate counts: source has more change rows than unique records
        assert sim_count("SELECT COUNT(*) FROM sim_changes") > sim_count("SELECT COUNT(*) FROM sim_posts")
        main = metrics.main_group_id(s)
        assert s.query(Member).filter_by(group_id=main).count() == 250
        st = s.execute(select(SyncState)).scalar_one()
        assert st.status == "ok" and st.coverage["complete"] is True and st.coverage["deferred"] == 0


def test_named_scenarios(seeded):
    with db.session_scope() as s:
        gid = metrics.main_group_id(s)
        by = {m.upstream_id: m for m in s.query(Member).filter(Member.upstream_id.like("syn-mem-scn-%"))}
        assert by["syn-mem-scn-new"].id in metrics.segment_members(s, "new_members", {"days": 14}, gid)
        assert by["syn-mem-scn-new"].id in metrics.segment_members(s, "pending_onboarding", {}, gid)
        sc = metrics.default_scope(s, 90, gid)
        silent = metrics.member_profile(s, by["syn-mem-scn-silent"].id, sc)
        assert silent["posts"] == 0 and silent["comments"] == 0 and silent["lessons_marked_complete"] == 24
        commenter = metrics.member_profile(s, by["syn-mem-scn-commenter"].id, sc)
        assert commenter["comments"] >= 40 and commenter["lessons_marked_complete"] <= 1
        assert by["syn-mem-scn-rejoin"].rejoin_count == 1 and by["syn-mem-scn-rejoin"].status == "active"
        assert by["syn-mem-scn-samename-a"].display_name == by["syn-mem-scn-samename-b"].display_name
        assert by["syn-mem-scn-samename-a"].id != by["syn-mem-scn-samename-b"].id
        items = {p.upstream_id: i for i, p in s.execute(select(SupportItem, Post).join(Post, Post.id == SupportItem.post_id))}
        assert items["syn-post-scn-unanswered"].first_response_at is None
        assert items["syn-post-scn-support"].label == "needs_support" and items["syn-post-scn-support"].priority == "high"
        assert items["syn-post-scn-answered"].first_response_by == "staff"
        iso_members = s.query(Member).filter(Member.upstream_id.like("syn-iso-%")).all()
        assert iso_members and all(m.group_id != gid for m in iso_members)


def test_partial_sync_and_auth_expiry_are_not_an_empty_community(seeded):
    st = get_store()
    st.add_post(author_id="syn-mem-scn-support", title="New q?", body="New question?")
    st.add_post(author_id="syn-mem-scn-support", title="Another?", body="Another question?")
    with db.session_scope() as s:
        before = s.query(Member).count()
        st.set_fault("auth_expired", remaining=1)
        res = sync.sync_once(s, get_adapter("simulator"))
        assert res["ok"] is False and res["status"] == "auth_expired"
        assert s.query(Member).count() == before  # nothing wiped
        state = s.execute(select(SyncState)).scalar_one()
        assert state.status == "auth_expired" and "auth_expired" in state.last_error
        # partial: first page succeeds, the next page fails
        st.set_fault("partial_sync", remaining=1)
        res = sync.sync_once(s, get_adapter("simulator"), page_size=1)
        assert res["status"] == "partial" and res["applied"] == 1
        res = sync.sync_once(s, get_adapter("simulator"))
        assert res["ok"] and res["status"] == "ok"
        assert s.query(Post).filter(Post.title.in_(["New q?", "Another?"])).count() == 2
        from app.models import Notification
        assert s.query(Notification).filter(Notification.dedupe_key == "sync:simulator").one().read is True


def test_edit_and_delete_propagate_without_double_counting(seeded):
    st = get_store()
    with db.session_scope() as s:
        n = s.query(func.count(Post.id)).scalar()
    st.edit_post("syn-post-scn-ambiguous", "Is the annual plan worth it compared to monthly?")
    st.delete_post("syn-post-scn-refund")
    with db.session_scope() as s:
        sync.sync_once(s, get_adapter("simulator"))
        p = s.query(Post).filter_by(upstream_id="syn-post-scn-ambiguous").one()
        assert p.version == 2 and p.edited_at is not None and "annual plan" in p.body
        assert s.query(Post).filter_by(upstream_id="syn-post-scn-refund").one().deleted_at is not None
        assert s.query(func.count(Post.id)).scalar() == n
