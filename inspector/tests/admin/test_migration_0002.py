"""Migration 0002 applies: schema version, new columns, table, indexes."""
from __future__ import annotations

from services import db


def test_user_version_is_2():
    assert db.current_version(db.get_writer()) >= 2


def test_users_has_recency_columns():
    cols = {r[1] for r in db.get_conn().execute("PRAGMA table_info(users)").fetchall()}
    assert {"last_login_at", "last_entry_at"} <= cols


def test_visitor_daily_table_exists():
    cols = {r[1] for r in db.get_conn().execute("PRAGMA table_info(visitor_daily)").fetchall()}
    assert {"date", "signed_in_hits", "anon_hits", "unique_signed_in", "unique_anon"} <= cols


def test_new_indexes_exist():
    names = {
        r[0]
        for r in db.get_conn().execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    assert {"ix_transitions_actor_ts", "ix_requests_requester", "ix_claims_assignee"} <= names
