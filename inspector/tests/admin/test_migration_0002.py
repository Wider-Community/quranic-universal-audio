"""Migration 0002 applies: schema version, new columns, table, indexes.

Sanity assertions on the full-chain DB plus a regression test that simulates a
pre-0002 DB (user_version = 1) and confirms the ALTER + CREATE statements land.
Without the simulate-and-upgrade test, inlining 0002 into 0001 would silently
pass — only fresh DBs would get the additions; existing live DBs at
user_version >= 1 would never replay 0001 and silently miss the new shape.
"""

from __future__ import annotations

import sqlite3

from services import db
from services.db import migrate


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
        for r in db.get_conn()
        .execute("SELECT name FROM sqlite_master WHERE type='index'")
        .fetchall()
    }
    assert {"ix_transitions_actor_ts", "ix_requests_requester", "ix_claims_assignee"} <= names


def test_existing_db_at_v1_gets_admin_users_additions():
    """Simulate the live bucket DB at ``user_version = 1`` — a ``users`` table
    WITHOUT recency columns and no ``visitor_daily`` table. Running the chain
    must apply 0002 and add the columns/table/indexes. An edit to 0001 inlining
    the additions would silently no-op here and leave them missing on live DBs.
    """
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        -- minimal pre-0002 ``users`` table (no last_login_at / last_entry_at)
        CREATE TABLE users (
            hf_user_id  TEXT PRIMARY KEY,
            login_cache TEXT,
            first_seen  TEXT,
            last_seen   TEXT
        );
        -- role_assignments is created in 0001 and read by 0003's first_seen
        -- backfill (UNION over granted_at). Without it the chain blows up
        -- at migration 0003.
        CREATE TABLE role_assignments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            hf_user_id  TEXT NOT NULL,
            role        TEXT NOT NULL,
            granted_at  TEXT NOT NULL,
            granted_by  TEXT,
            revoked_at  TEXT,
            revoked_by  TEXT,
            reason      TEXT
        );
        -- minimal pre-0002 base tables that 0002's indexes (and downstream
        -- migrations) reference. 0011 drops prefetch_purge_at, 0014 ALTERs
        -- channels, 0015 nulls bitrate_kbps_nominal on deliveries.
        CREATE TABLE transitions (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            slug      TEXT,
            event     TEXT NOT NULL,
            actor_id  TEXT,
            ts        TEXT NOT NULL
        );
        CREATE TABLE requests (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            slug          TEXT,
            requester_id  TEXT NOT NULL,
            submitted_at  TEXT NOT NULL
        );
        CREATE TABLE claims (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            slug        TEXT NOT NULL,
            assignee_id TEXT NOT NULL,
            claimed_at  TEXT NOT NULL,
            released_at TEXT
        );
        CREATE TABLE delivery_states (
            slug              TEXT PRIMARY KEY,
            state             TEXT NOT NULL,
            prefetch_purge_at TEXT
        );
        CREATE TABLE channels (
            slug          TEXT PRIMARY KEY,
            short         TEXT NOT NULL,
            name          TEXT NOT NULL,
            host_patterns TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE deliveries (
            slug                 TEXT PRIMARY KEY,
            bitrate_mode         TEXT NOT NULL DEFAULT 'unknown',
            bitrate_kbps_nominal INTEGER
        );
        PRAGMA user_version = 1;
        """
    )
    pre_users = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    assert "last_login_at" not in pre_users
    assert "last_entry_at" not in pre_users
    assert (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='visitor_daily'"
        ).fetchone()
        is None
    )

    version = migrate.run_migrations(conn)
    assert version >= 2

    post_users = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    assert {"last_login_at", "last_entry_at"} <= post_users
    visitor_cols = {r[1] for r in conn.execute("PRAGMA table_info(visitor_daily)").fetchall()}
    assert {
        "date",
        "signed_in_hits",
        "anon_hits",
        "unique_signed_in",
        "unique_anon",
    } <= visitor_cols
    index_names = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    }
    assert {"ix_transitions_actor_ts", "ix_requests_requester", "ix_claims_assignee"} <= index_names
    conn.close()
