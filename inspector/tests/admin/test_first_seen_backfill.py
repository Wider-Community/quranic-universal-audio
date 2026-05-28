"""Migration 0003: first_seen recompute from earliest historical evidence.

Exercises the canonical SQL (the same file build() applies on a fresh migration)
against seeded data. The autouse DB fixture already applied 0003 on an empty DB
(a no-op); here we seed late first_seen + earlier activity and re-run it."""
from __future__ import annotations

from pathlib import Path

from services import db
from services.db import repo_access

_SQL = (
    Path(__file__).resolve().parents[2]
    / "services" / "db" / "migrations" / "0003_backfill_first_seen.sql"
).read_text(encoding="utf-8")


def _first_seen(uid: str) -> str | None:
    row = db.get_conn().execute(
        "SELECT first_seen FROM users WHERE hf_user_id = ?", (uid,)
    ).fetchone()
    return row[0] if row else None


def _backfill() -> None:
    with db.transaction() as c:
        c.execute(_SQL)


def test_pulls_back_to_earliest_transition():
    with db.transaction() as c:
        repo_access.ensure_user("u1", login="a")  # first_seen = now (late)
        c.execute("INSERT INTO transitions(id,ts,event,actor_id) VALUES('t1','2025-01-02T00:00:00Z','x','u1')")
        c.execute("INSERT INTO transitions(id,ts,event,actor_id) VALUES('t2','2024-06-01T00:00:00Z','x','u1')")
    late = _first_seen("u1")
    _backfill()
    assert _first_seen("u1") == "2024-06-01T00:00:00Z"
    assert _first_seen("u1") < late


def test_min_across_sources_request_wins():
    with db.transaction() as c:
        repo_access.ensure_user("u2", login="b")
        c.execute("INSERT INTO requests(id,kind,requester_id,submitted_at,status) VALUES('r1','k','u2','2025-03-01T00:00:00Z','pending')")
        c.execute("INSERT INTO transitions(id,ts,event,actor_id) VALUES('t3','2025-09-01T00:00:00Z','x','u2')")
    _backfill()
    assert _first_seen("u2") == "2025-03-01T00:00:00Z"


def test_claim_source(seed_state):
    seed_state("sx", state="under_review", assignee_hf_id="u5", assignee_login="e")
    with db.transaction() as c:
        c.execute(
            "INSERT INTO claims(slug,assignee_id,assignee_login_snapshot,claimed_at,released_at) "
            "VALUES('sx','u5','e','2024-02-02T00:00:00Z','2024-03-01T00:00:00Z')"
        )
    _backfill()
    assert _first_seen("u5") == "2024-02-02T00:00:00Z"


def test_no_activity_unchanged():
    with db.transaction():
        repo_access.ensure_user("u3", login="c")
    before = _first_seen("u3")
    _backfill()
    assert _first_seen("u3") == before


def test_idempotent_and_only_backwards():
    with db.transaction() as c:
        repo_access.ensure_user("u4", login="d")
        c.execute("INSERT INTO transitions(id,ts,event,actor_id) VALUES('t4','2024-01-01T00:00:00Z','x','u4')")
    _backfill()
    once = _first_seen("u4")
    _backfill()  # re-run finds nothing earlier
    assert _first_seen("u4") == once == "2024-01-01T00:00:00Z"
