"""Migration 0010 applies: guide_views table + per-user index."""
from __future__ import annotations

from services import db


def test_user_version_is_at_least_10():
    assert db.current_version(db.get_writer()) >= 10


def test_guide_views_table_shape():
    cols = {r[1] for r in db.get_conn().execute("PRAGMA table_info(guide_views)").fetchall()}
    assert {"view_key", "hf_user_id", "viewed_at"} <= cols


def test_guide_views_user_index_exists():
    names = {
        r[0]
        for r in db.get_conn().execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    assert "ix_guide_views_user" in names
