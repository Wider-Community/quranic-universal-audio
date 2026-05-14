"""Tests for ``services/activity_state`` — bucket-resident store holding
per-user dismissals + global tombstones for the activity rails.

This is the codebase's 5th bucket store (alongside state, access, catalog,
audit) and follows the same hydrate / snapshot / write-through pattern.
"""

from __future__ import annotations

import pytest

from scripts.lib.schemas import Actor, Role


@pytest.fixture
def fresh_state(tmp_path, monkeypatch):
    """Per-test FilesystemBackend so each test starts with a clean store."""
    from services import activity_state as activity_state_service
    from services import hf_bucket as _hf_bucket

    monkeypatch.setenv("INSPECTOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INSPECTOR_BACKEND", "filesystem")
    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))

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
    assert snap.dismissals == {}


def test_hydrate_loads_existing_file(tmp_path, monkeypatch):
    from services import activity_state as activity_state_service
    from services import hf_bucket as _hf_bucket
    from services import storage_paths

    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)
    backend.write_json_atomic(
        storage_paths.activity_state_path(),
        {
            "deleted": ["aaaa1111", "bbbb2222"],
            "dismissals": {"u-1": ["cccc3333"], "u-2": ["dddd4444"]},
        },
    )
    activity_state_service.hydrate()
    snap = activity_state_service.snapshot()
    assert snap.deleted == ["aaaa1111", "bbbb2222"]
    assert snap.dismissals == {"u-1": ["cccc3333"], "u-2": ["dddd4444"]}
    _hf_bucket.reset_backend()


# ---------------------------------------------------------------------------
# Per-user dismissals
# ---------------------------------------------------------------------------


def test_dismiss_records_per_user(fresh_state, monkeypatch):
    svc, _ = fresh_state
    # Silence audit writes; we test the audit linkage separately.
    from services import audit as audit_service

    calls = []
    monkeypatch.setattr(
        audit_service, "append", lambda **kw: calls.append(kw),
    )

    actor_a = _actor("u-A", role="maintainer", login="alice")
    actor_b = _actor("u-B", role="maintainer", login="bob")

    svc.dismiss("abc123", actor=actor_a)
    svc.dismiss("abc123", actor=actor_b)
    svc.dismiss("xyz789", actor=actor_a)

    snap = svc.snapshot()
    assert sorted(snap.dismissals["u-A"]) == ["abc123", "xyz789"]
    assert snap.dismissals["u-B"] == ["abc123"]


def test_is_dismissed_scoped_to_user(fresh_state, monkeypatch):
    svc, _ = fresh_state
    from services import audit as audit_service
    monkeypatch.setattr(audit_service, "append", lambda **kw: None)

    svc.dismiss("abc123", actor=_actor("u-A", role="maintainer"))
    assert svc.is_dismissed("abc123", "u-A") is True
    assert svc.is_dismissed("abc123", "u-B") is False
    assert svc.is_dismissed("nope", "u-A") is False


def test_undismiss_removes_only_for_caller(fresh_state, monkeypatch):
    svc, _ = fresh_state
    from services import audit as audit_service
    monkeypatch.setattr(audit_service, "append", lambda **kw: None)

    actor_a = _actor("u-A", role="maintainer")
    actor_b = _actor("u-B", role="maintainer")
    svc.dismiss("shared", actor=actor_a)
    svc.dismiss("shared", actor=actor_b)
    svc.undismiss("shared", actor=actor_a)

    assert svc.is_dismissed("shared", "u-A") is False
    assert svc.is_dismissed("shared", "u-B") is True


def test_dismiss_writes_audit_record(fresh_state, monkeypatch):
    svc, _ = fresh_state
    from services import audit as audit_service
    calls = []
    monkeypatch.setattr(
        audit_service, "append", lambda **kw: calls.append(kw),
    )
    actor = _actor("u-A", role="maintainer", login="alice")
    svc.dismiss("abc123", actor=actor)

    assert len(calls) == 1
    assert calls[0]["event"] == "activity.dismissed"
    assert calls[0]["actor"] is actor
    assert calls[0]["payload"] == {"audit_id": "abc123"}


def test_dismiss_idempotent(fresh_state, monkeypatch):
    svc, _ = fresh_state
    from services import audit as audit_service
    monkeypatch.setattr(audit_service, "append", lambda **kw: None)

    actor = _actor("u-A", role="maintainer")
    svc.dismiss("abc123", actor=actor)
    svc.dismiss("abc123", actor=actor)

    assert svc.snapshot().dismissals["u-A"] == ["abc123"]


# ---------------------------------------------------------------------------
# Global tombstones
# ---------------------------------------------------------------------------


def test_delete_records_tombstone(fresh_state, monkeypatch):
    svc, _ = fresh_state
    from services import audit as audit_service
    calls = []
    monkeypatch.setattr(audit_service, "append", lambda **kw: calls.append(kw))

    actor = _actor("u-O", role="owner", login="owen")
    svc.delete("abc123", actor=actor, reason="content removed per request")

    snap = svc.snapshot()
    assert snap.deleted == ["abc123"]
    assert calls[0]["event"] == "admin.activity_deleted"
    assert calls[0]["reason"] == "content removed per request"
    assert calls[0]["payload"] == {"audit_id": "abc123"}


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


def test_writes_persist_to_bucket(fresh_state, monkeypatch):
    svc, backend = fresh_state
    from services import audit as audit_service
    from services import storage_paths
    monkeypatch.setattr(audit_service, "append", lambda **kw: None)

    svc.dismiss("abc123", actor=_actor("u-A", role="maintainer"))
    svc.delete("xyz789", actor=_actor("u-O", role="owner"), reason="ten chars+")

    raw = backend.read_json(storage_paths.activity_state_path())
    assert raw["deleted"] == ["xyz789"]
    assert raw["dismissals"] == {"u-A": ["abc123"]}
