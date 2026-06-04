"""Migration 0010 applies: guide_views table + per-user index.

Fresh-chain checks plus a simulated pre-0010 DB (user_version = 9) to regress
inlining 0010 into 0001 (which would silently no-op on existing live DBs).
"""

from __future__ import annotations

import sqlite3

from services import db
from services.db import migrate


def test_user_version_is_at_least_10():
    assert db.current_version(db.get_writer()) >= 10


def test_guide_views_table_shape():
    cols = {r[1] for r in db.get_conn().execute("PRAGMA table_info(guide_views)").fetchall()}
    assert {"view_key", "hf_user_id", "viewed_at"} <= cols


def test_guide_views_user_index_exists():
    names = {
        r[0]
        for r in db.get_conn()
        .execute("SELECT name FROM sqlite_master WHERE type='index'")
        .fetchall()
    }
    assert "ix_guide_views_user" in names


def test_existing_db_at_v9_gets_guide_views():
    """Simulate a live bucket DB at ``user_version = 9`` without ``guide_views``.
    Running the chain must apply 0010 and add the table + index."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE users (
            hf_user_id  TEXT PRIMARY KEY,
            login_cache TEXT
        );
        -- Minimal stubs the post-0009 downstream migrations rely on.
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
        PRAGMA user_version = 9;
        """
    )
    assert (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='guide_views'"
        ).fetchone()
        is None
    )

    version = migrate.run_migrations(conn)
    assert version >= 10

    cols = {r[1] for r in conn.execute("PRAGMA table_info(guide_views)").fetchall()}
    assert {"view_key", "hf_user_id", "viewed_at"} <= cols
    index_names = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    }
    assert "ix_guide_views_user" in index_names
    conn.close()
