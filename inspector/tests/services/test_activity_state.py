"""Tests for ``services/activity_state`` — facade over the global-tombstone
table that backs the owner-only "delete from public feed" action.

Only the global tombstone path lives here; per-user dismissals do not exist
since the discovery surface is the Admin dashboard tabs.
"""

from __future__ import annotations

from datetime import UTC

import pytest

from qua_shared.schemas import Actor, Role


@pytest.fixture
def fresh_state():
    """Per-test isolation comes from the autouse ``_substrate_db`` fixture;
    this fixture just exposes the activity_state service for readability."""
    from services import activity_state as activity_state_service

    yield activity_state_service


def _actor(hf_user_id="u-admin", role="owner", login="admin"):
    return Actor(hf_user_id=hf_user_id, login_at_time=login, role=Role(role))


# ---------------------------------------------------------------------------
# Hydrate
# ---------------------------------------------------------------------------


def test_hydrate_empty_when_no_file(fresh_state):
    snap = fresh_state.snapshot()
    assert snap.deleted == []


# ---------------------------------------------------------------------------
# Global tombstones
# ---------------------------------------------------------------------------


def test_delete_records_tombstone(fresh_state):
    from datetime import datetime, timedelta, timezone

    from services.db import repo_transitions

    actor = _actor("u-O", role="owner", login="owen")
    cutoff_iso = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
    fresh_state.delete("abc123", actor=actor, reason="content removed per request")

    snap = fresh_state.snapshot()
    assert snap.deleted == ["abc123"]

    rows = [r for r in repo_transitions.since(cutoff_iso) if r["event"] == "admin.activity_deleted"]
    assert len(rows) == 1
    assert rows[0]["reason"] == "content removed per request"
    assert rows[0]["payload"] == {"audit_id": "abc123"}
    assert rows[0]["actor"]["hf_user_id"] == "u-O"


def test_is_deleted_predicate(fresh_state, monkeypatch):
    from services import audit as audit_service

    monkeypatch.setattr(audit_service, "append", lambda **kw: None)

    fresh_state.delete("abc123", actor=_actor("u-O", role="owner"), reason="ten chars+")
    assert fresh_state.is_deleted("abc123") is True
    assert fresh_state.is_deleted("other") is False


def test_delete_idempotent(fresh_state, monkeypatch):
    from services import audit as audit_service

    monkeypatch.setattr(audit_service, "append", lambda **kw: None)

    actor = _actor("u-O", role="owner")
    fresh_state.delete("abc123", actor=actor, reason="initial reason text")
    fresh_state.delete("abc123", actor=actor, reason="second time around")
    assert fresh_state.snapshot().deleted == ["abc123"]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_writes_persist_to_substrate(fresh_state, monkeypatch):
    """Delete persists into the SQLite substrate (read back via snapshot)."""
    from services import audit as audit_service

    monkeypatch.setattr(audit_service, "append", lambda **kw: None)

    fresh_state.delete("xyz789", actor=_actor("u-O", role="owner"), reason="ten chars+")

    snap = fresh_state.snapshot()
    assert snap.deleted == ["xyz789"]
