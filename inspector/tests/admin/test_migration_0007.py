"""Migration 0007 applies: mark-ready submission columns reach existing DBs.

Regression guard for the bug where the ``mark_ready_*`` columns were inlined
into ``0001_init.sql`` instead of shipped as an additive migration. Every
deployed/dev/local DB is already past ``user_version`` 1, so 0001 never re-runs
and the columns never reached live data — the admin Reviews General drawer
detail query (which SELECTs them) 500'd with ``no such column``. The columns
MUST arrive via an ALTER migration to land on an existing DB.
"""

from __future__ import annotations

import sqlite3

from services import db
from services.db import migrate

_MARK_READY_COLS = {
    "mark_ready_checklist",
    "mark_ready_comment_checks",
    "mark_ready_comment_issues",
}


def _claims_cols(conn) -> set[str]:
    return {r[1] for r in conn.execute("PRAGMA table_info(claims)").fetchall()}


def test_user_version_is_at_least_7():
    assert db.current_version(db.get_writer()) >= 7


def test_fresh_db_has_mark_ready_columns():
    """0001 no longer creates these; 0007 adds them. A fresh full-chain DB must
    end up with all three (and no double-create error along the way)."""
    assert _MARK_READY_COLS <= _claims_cols(db.get_conn())


def test_existing_db_at_v6_gets_mark_ready_columns():
    """The core regression: simulate the live bucket DB — a ``claims`` table
    WITHOUT the submission columns, stamped ``user_version = 6`` (built from the
    pre-0007 init, before the columns existed). Running the migration chain must
    apply 0007 and add the columns. An edit to an already-applied migration
    would silently no-op here and leave the columns missing."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE claims (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            slug                    TEXT NOT NULL,
            assignee_id             TEXT NOT NULL,
            assignee_login_snapshot TEXT,
            claimed_at              TEXT NOT NULL,
            released_at             TEXT,
            marked_ready_at         TEXT,
            close_reason            TEXT,
            opened_by_transition_id TEXT,
            closed_by_transition_id TEXT
        );
        -- Minimal stand-in for the real 0001 delivery_states so the full chain
        -- (incl. 0011's DROP COLUMN prefetch_purge_at) applies; a real v6 DB has
        -- this table with the column.
        CREATE TABLE delivery_states (
            slug              TEXT PRIMARY KEY,
            state             TEXT NOT NULL,
            prefetch_purge_at TEXT
        );
        -- Minimal stand-in for 0001's catalog vocab + deliveries so migration
        -- 0014 (releases) can ALTER channels and reference deliveries(slug).
        CREATE TABLE channels (
            slug          TEXT PRIMARY KEY,
            short         TEXT NOT NULL,
            name          TEXT NOT NULL,
            host_patterns TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE deliveries (
            slug                 TEXT PRIMARY KEY,
            bitrate_mode         TEXT NOT NULL DEFAULT 'unknown',
            -- 0015 nulls kbps on mixed rows, so the column must exist
            -- even in this minimal v6 stub.
            bitrate_kbps_nominal INTEGER
        );
        PRAGMA user_version = 6;
        """
    )
    assert _MARK_READY_COLS.isdisjoint(_claims_cols(conn))  # pre-condition

    version = migrate.run_migrations(conn)

    assert version >= 7
    assert _MARK_READY_COLS <= _claims_cols(conn)
    conn.close()
