"""Smoke tests for the SQLite substrate spine: migrations, txn primitives,
db_seq bumping, savepoint nesting, and the partial-unique invariants the
schema is supposed to enforce."""

from __future__ import annotations

import sqlite3

import pytest

from services import db
from services.db import migrate as _migrate

# Highest migration number on disk — the version a fresh DB lands at. Derived
# (not hard-coded) so adding a migration doesn't break these smoke tests.
_LATEST_VERSION = max(n for n, _ in _migrate._discover())


@pytest.fixture
def fresh_db(tmp_path):
    db.set_db_path_for_test(tmp_path / "spine.db")
    db.init_db()
    yield
    db.reset()


def test_migration_creates_all_tables(fresh_db):
    assert db.current_version(db.get_writer()) == _LATEST_VERSION
    conn = db.get_conn()
    names = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    expected = {
        "db_meta",
        "users",
        "role_assignments",
        "riwayahs",
        "styles",
        "sources",
        "channels",
        "recording_contexts",
        "catalog_meta",
        "catalog_aliases",
        "reciters",
        "deliveries",
        "transitions",
        "delivery_states",
        "claims",
        "requests",
        "activity_tombstones",
        "visitor_daily",
        "request_views",
        "review_views",
    }
    assert expected <= names
    # ``activity_dismissals`` was dropped in migration 0006 (admin notifs rail).
    assert "activity_dismissals" not in names


def test_rerun_migrations_is_noop(fresh_db):
    # second run should not error (no CREATE TABLE re-execution)
    assert db.run_migrations(db.get_writer()) == _LATEST_VERSION


def test_commit_bumps_db_seq(fresh_db):
    start = db.current_db_seq()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO users(hf_user_id, login_cache) VALUES (?, ?)",
            ("u1", "alice"),
        )
    assert db.current_db_seq() == start + 1
    # reader sees the committed row immediately (read-after-write)
    row = db.get_conn().execute("SELECT login_cache FROM users WHERE hf_user_id = 'u1'").fetchone()
    assert row[0] == "alice"


def test_rollback_on_error_leaves_no_rows_and_no_seq_bump(fresh_db):
    start = db.current_db_seq()
    with pytest.raises(ValueError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO users(hf_user_id, login_cache) VALUES (?, ?)",
                ("u2", "bob"),
            )
            raise ValueError("boom")
    assert db.current_db_seq() == start
    assert (
        db.get_conn().execute("SELECT COUNT(*) FROM users WHERE hf_user_id = 'u2'").fetchone()[0]
        == 0
    )


def test_nested_transaction_savepoint_partial_rollback(fresh_db):
    # outer commits; inner failure rolls back only the inner work.
    with db.transaction() as conn:
        conn.execute("INSERT INTO users(hf_user_id) VALUES ('outer')")
        try:
            with db.transaction() as conn2:
                conn2.execute("INSERT INTO users(hf_user_id) VALUES ('inner')")
                raise RuntimeError("inner boom")
        except RuntimeError:
            pass
    users = {r[0] for r in db.get_conn().execute("SELECT hf_user_id FROM users").fetchall()}
    assert "outer" in users
    assert "inner" not in users


def test_nested_transaction_single_commit_seq(fresh_db):
    # a nested transaction does NOT bump db_seq twice — one logical commit.
    start = db.current_db_seq()
    with db.transaction() as conn:
        conn.execute("INSERT INTO users(hf_user_id) VALUES ('a')")
        with db.transaction() as conn2:
            conn2.execute("INSERT INTO users(hf_user_id) VALUES ('b')")
    assert db.current_db_seq() == start + 1


def test_foreign_keys_enforced(fresh_db):
    """delivery.reciter_id REFERENCES reciters(reciter_id) is enforced under
    PRAGMA foreign_keys=ON. Seed every other FK target so the rejection is
    unambiguously attributed to the reciters FK (and not a stray vocab one)."""
    with db.transaction() as conn:
        conn.execute("INSERT INTO users(hf_user_id) VALUES ('u1')")
        conn.execute("INSERT INTO riwayahs(slug,short,name) VALUES ('hafs','h','Hafs')")
        conn.execute("INSERT INTO styles(slug,short,name) VALUES ('murattal','m','Mur')")
        conn.execute("INSERT INTO sources(slug,name) VALUES ('src','Src')")
        conn.execute("INSERT INTO channels(slug,short,name) VALUES ('ch','c','Ch')")
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO deliveries(slug, reciter_id, riwayah, style, source, "
                "channel, audio_category, chapter_count, added_at, added_by_hf_id) "
                "VALUES ('s1','nope','hafs','murattal','src','ch','by_surah',114,"
                "'2026-01-01T00:00:00Z','u1')"
            )


def test_one_open_claim_per_slug(fresh_db):
    with db.transaction() as conn:
        conn.execute("INSERT INTO users(hf_user_id) VALUES ('u1')")
        conn.execute("INSERT INTO users(hf_user_id) VALUES ('u2')")
        conn.execute("INSERT INTO reciters(reciter_id, name_en) VALUES ('r','R')")
        conn.execute("INSERT INTO riwayahs(slug,short,name) VALUES ('hafs','h','Hafs')")
        conn.execute("INSERT INTO styles(slug,short,name) VALUES ('mur','m','Mur')")
        conn.execute("INSERT INTO sources(slug,name) VALUES ('src','Src')")
        conn.execute("INSERT INTO channels(slug,short,name) VALUES ('ch','c','Ch')")
        conn.execute(
            "INSERT INTO deliveries(slug, reciter_id, riwayah, style, source, channel,"
            " audio_category, chapter_count, added_at, added_by_hf_id) VALUES "
            "('d1','r','hafs','mur','src','ch','by_surah',114,'2026-01-01T00:00:00Z','u1')"
        )
        conn.execute(
            "INSERT INTO claims(slug, assignee_id, claimed_at) VALUES "
            "('d1','u1','2026-01-01T00:00:00Z')"
        )
    # second OPEN claim on the same slug must violate the partial-unique index
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO claims(slug, assignee_id, claimed_at) VALUES "
                "('d1','u2','2026-01-02T00:00:00Z')"
            )
    # but once the first is released, a new open claim is allowed
    with db.transaction() as conn:
        conn.execute("UPDATE claims SET released_at='2026-01-03T00:00:00Z' WHERE slug='d1'")
        conn.execute(
            "INSERT INTO claims(slug, assignee_id, claimed_at) VALUES "
            "('d1','u2','2026-01-03T00:00:00Z')"
        )


def test_pending_request_unique_only_when_slug_present(fresh_db):
    with db.transaction() as conn:
        conn.execute("INSERT INTO users(hf_user_id) VALUES ('u1')")
        conn.execute("INSERT INTO reciters(reciter_id, name_en) VALUES ('r','R')")
        conn.execute("INSERT INTO riwayahs(slug,short,name) VALUES ('hafs','h','Hafs')")
        conn.execute("INSERT INTO styles(slug,short,name) VALUES ('mur','m','Mur')")
        conn.execute("INSERT INTO sources(slug,name) VALUES ('src','Src')")
        conn.execute("INSERT INTO channels(slug,short,name) VALUES ('ch','c','Ch')")
        conn.execute(
            "INSERT INTO deliveries(slug, reciter_id, riwayah, style, source, channel,"
            " audio_category, chapter_count, added_at, added_by_hf_id) VALUES "
            "('d1','r','hafs','mur','src','ch','by_surah',114,'2026-01-01T00:00:00Z','u1')"
        )
        conn.execute(
            "INSERT INTO requests(id, kind, slug, requester_id, submitted_at, status) "
            "VALUES ('rq1','existing_combo_edit','d1','u1','2026-01-01T00:00:00Z','pending')"
        )
    # second pending request for the same slug → violation
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO requests(id, kind, slug, requester_id, submitted_at, status)"
                " VALUES ('rq2','existing_combo_edit','d1','u1','2026-01-02T00:00:00Z','pending')"
            )
    # two slugless (new_reciter) pending requests are both allowed
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO requests(id, kind, slug, requester_id, submitted_at, status)"
            " VALUES ('rq3','new_reciter',NULL,'u1','2026-01-02T00:00:00Z','pending')"
        )
        conn.execute(
            "INSERT INTO requests(id, kind, slug, requester_id, submitted_at, status)"
            " VALUES ('rq4','new_reciter',NULL,'u1','2026-01-02T00:00:00Z','pending')"
        )


def test_one_active_role_per_user(fresh_db):
    with db.transaction() as conn:
        conn.execute("INSERT INTO users(hf_user_id) VALUES ('u1')")
        conn.execute(
            "INSERT INTO role_assignments(hf_user_id, role, granted_at) "
            "VALUES ('u1','maintainer','2026-01-01T00:00:00Z')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO role_assignments(hf_user_id, role, granted_at) "
                "VALUES ('u1','owner','2026-01-02T00:00:00Z')"
            )


def test_visibility_discarded_requires_reason(fresh_db):
    with db.transaction() as conn:
        conn.execute("INSERT INTO users(hf_user_id) VALUES ('u1')")
        conn.execute("INSERT INTO reciters(reciter_id, name_en) VALUES ('r','R')")
        conn.execute("INSERT INTO riwayahs(slug,short,name) VALUES ('hafs','h','Hafs')")
        conn.execute("INSERT INTO styles(slug,short,name) VALUES ('mur','m','Mur')")
        conn.execute("INSERT INTO sources(slug,name) VALUES ('src','Src')")
        conn.execute("INSERT INTO channels(slug,short,name) VALUES ('ch','c','Ch')")
        conn.execute(
            "INSERT INTO deliveries(slug, reciter_id, riwayah, style, source, channel,"
            " audio_category, chapter_count, added_at, added_by_hf_id) VALUES "
            "('d1','r','hafs','mur','src','ch','by_surah',114,'2026-01-01T00:00:00Z','u1')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO delivery_states(slug, state, state_since, visibility) "
                "VALUES ('d1','catalogued','2026-01-01T00:00:00Z','discarded')"
            )
