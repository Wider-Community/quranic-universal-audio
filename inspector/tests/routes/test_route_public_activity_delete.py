"""Tests for ``DELETE /api/public/activity/<audit_id>`` — owner-only
tombstone on a public-feed card. The admin notifications rail (and its
dismiss / undismiss endpoints) was retired; this delete is the only
remaining mutation against the activity sidecars.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("INSPECTOR_SESSION_SECRET", "0" * 64)

_HEADERS = {"Content-Type": "application/json", "Origin": "http://localhost"}


@pytest.fixture(autouse=True)
def _isolated_backend(tmp_path, monkeypatch):
    """Per-test FilesystemBackend so delete writes never reach the
    real dev bucket."""
    from services import activity_state as activity_state_service
    from services import hf_bucket as _hf_bucket

    monkeypatch.setenv("INSPECTOR_BACKEND", "filesystem")
    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)
    activity_state_service.hydrate()
    yield
    _hf_bucket.reset_backend()


def _silence_audit(monkeypatch):
    from services import audit as audit_service
    monkeypatch.setattr(audit_service, "append", lambda **kw: None)


def test_delete_public_anonymous_returns_401(flask_client):
    res = flask_client.delete(
        "/api/public/activity/abc123",
        data=json.dumps({"reason": "ten chars or more here"}),
        headers=_HEADERS,
    )
    assert res.status_code == 401


def test_delete_public_contributor_returns_403(signed_in_client, monkeypatch):
    _silence_audit(monkeypatch)
    client, _ = signed_in_client(role="contributor")
    res = client.delete(
        "/api/public/activity/abc123",
        data=json.dumps({"reason": "ten chars or more here"}),
        headers=_HEADERS,
    )
    assert res.status_code == 403


def test_delete_public_maintainer_returns_403(signed_in_client, monkeypatch):
    """Delete is owner-only — maintainers can't tombstone public activity."""
    _silence_audit(monkeypatch)
    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M")
    res = client.delete(
        "/api/public/activity/abc123",
        data=json.dumps({"reason": "ten chars or more here"}),
        headers=_HEADERS,
    )
    assert res.status_code == 403


def test_delete_public_owner_happy_path(signed_in_client, monkeypatch):
    from services import activity_state as activity_state_service
    _silence_audit(monkeypatch)
    client, _ = signed_in_client(role="owner", hf_user_id="u-O", login="owen")
    res = client.delete(
        "/api/public/activity/abc123",
        data=json.dumps({"reason": "content removed for legal request"}),
        headers=_HEADERS,
    )
    assert res.status_code == 200
    assert activity_state_service.is_deleted("abc123") is True


def test_delete_public_short_reason_returns_400(signed_in_client, monkeypatch):
    _silence_audit(monkeypatch)
    client, _ = signed_in_client(role="owner", hf_user_id="u-O")
    res = client.delete(
        "/api/public/activity/abc123",
        data=json.dumps({"reason": "too short"}),
        headers=_HEADERS,
    )
    assert res.status_code == 400


def test_delete_public_missing_origin_returns_403(signed_in_client, monkeypatch):
    _silence_audit(monkeypatch)
    client, _ = signed_in_client(role="owner", hf_user_id="u-O")
    res = client.delete(
        "/api/public/activity/abc123",
        data=json.dumps({"reason": "content removed for legal request"}),
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 403
