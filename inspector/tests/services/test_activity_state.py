"""Tests for ``services/activity_state`` — facade over the global-tombstone
sidecar that backs the owner-only "delete from public feed" action.

Per-user dismissals were dropped alongside the admin notifications rail
(the Admin dashboard tabs are the discovery surface now); only the global
tombstone path remains here.
"""

from __future__ import annotations

import pytest

from qua_shared.schemas import Actor, Role


@pytest.fixture
def fresh_state(tmp_path):
    """Per-test FilesystemBackend so each test starts with a clean store."""
    from services import activity_state as activity_state_service
    from services import hf_bucket as _hf_bucket

    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)
    activity_state_service.hydrate()

    yield activity_state_service, backend

    _hf_bucket.reset_backend()


def _actor(hf_user_id="u-admin", role="owner", login="admin"):
    return Actor(hf_user_id=hf_user_id, login_at_time=login, role=Role(role))


# ---------------------------------------------------------------------------
# Hydrate
# ---------------------------------------------------------------------------


def test_hydrate_empty_when_no_file(fresh_state):
    svc, _ = fresh_state
    snap = svc.snapshot()
    assert snap.deleted == []


# ---------------------------------------------------------------------------
# Global tombstones
# ---------------------------------------------------------------------------


def test_delete_records_tombstone(fresh_state):
    svc, _ = fresh_state
    from datetime import datetime, timedelta, timezone

    from services.db import repo_transitions

    actor = _actor("u-O", role="owner", login="owen")
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    svc.delete("abc123", actor=actor, reason="content removed per request")

    snap = svc.snapshot()
    assert snap.deleted == ["abc123"]

    rows = [
        r for r in repo_transitions.since(cutoff_iso)
        if r["event"] == "admin.activity_deleted"
    ]
    assert len(rows) == 1
    assert rows[0]["reason"] == "content removed per request"
    assert rows[0]["payload"] == {"audit_id": "abc123"}
    assert rows[0]["actor"]["hf_user_id"] == "u-O"


def test_is_deleted_predicate(fresh_state, monkeypatch):
    svc, _ = fresh_state
    from services import audit as audit_service
    monkeypatch.setattr(audit_service, "append", lambda **kw: None)

    svc.delete("abc123", actor=_actor("u-O", role="owner"), reason="ten chars+")
    assert svc.is_deleted("abc123") is True
    assert svc.is_deleted("other") is False


def test_delete_idempotent(fresh_state, monkeypatch):
    svc, _ = fresh_state
    from services import audit as audit_service
    monkeypatch.setattr(audit_service, "append", lambda **kw: None)

    actor = _actor("u-O", role="owner")
    svc.delete("abc123", actor=actor, reason="initial reason text")
    svc.delete("abc123", actor=actor, reason="second time around")
    assert svc.snapshot().deleted == ["abc123"]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_writes_persist_to_substrate(fresh_state, monkeypatch):
    """Delete persists into the SQLite substrate (read back via snapshot)."""
    svc, _ = fresh_state
    from services import audit as audit_service
    monkeypatch.setattr(audit_service, "append", lambda **kw: None)

    svc.delete("xyz789", actor=_actor("u-O", role="owner"), reason="ten chars+")

    snap = svc.snapshot()
    assert snap.deleted == ["xyz789"]
