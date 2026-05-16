"""Admin/owner activity-rail endpoint tests.

Covers ``/api/admin/activity`` (GET feed + POST dismiss/undismiss) plus
``/api/public/activity/<audit_id>`` DELETE (owner-only tombstone).
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("INSPECTOR_SESSION_SECRET", "0" * 64)

_HEADERS = {"Content-Type": "application/json", "Origin": "http://localhost"}


@pytest.fixture(autouse=True)
def _isolated_backend(tmp_path, monkeypatch):
    """Per-test FilesystemBackend so dismiss/delete writes never reach the
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


def _install_audit_records(monkeypatch, records):
    from services import public_activity
    monkeypatch.setattr(
        public_activity, "_iter_partitions",
        lambda months=2: iter(records),
    )


def _install_catalog(monkeypatch, name_by_slug):
    from services import catalog as catalog_service
    monkeypatch.setattr(
        catalog_service, "display_name",
        lambda slug: name_by_slug.get(slug),
    )
    monkeypatch.setattr(
        catalog_service, "find_delivery", lambda slug: None,
    )


def _reset_activity_state():
    from scripts.lib.schemas import ActivityState
    from services import activity_state as activity_state_service
    with activity_state_service._store_lock:  # type: ignore[attr-defined]
        activity_state_service._store = ActivityState()  # type: ignore[attr-defined]


def _record(event, *, slug="husary_qdc", ts="2026-05-13T12:00:00+00:00",
            actor_hf="u-A", actor_login="alice", actor_role="maintainer",
            result="ok"):
    return {
        "event": event,
        "slug": slug,
        "ts": ts,
        "result": result,
        "actor": {
            "hf_user_id": actor_hf,
            "login_at_time": actor_login,
            "role": actor_role,
        },
    }


def _silence_audit(monkeypatch):
    from services import audit as audit_service
    monkeypatch.setattr(audit_service, "append", lambda **kw: None)


def setup_function(_func):
    _reset_activity_state()


def teardown_function(_func):
    _reset_activity_state()


# ---------------------------------------------------------------------------
# GET /api/admin/activity
# ---------------------------------------------------------------------------


def test_admin_feed_anonymous_returns_401(flask_client, monkeypatch):
    _install_audit_records(monkeypatch, [])
    _install_catalog(monkeypatch, {})
    res = flask_client.get("/api/admin/activity")
    assert res.status_code == 401


def test_admin_feed_contributor_returns_403(signed_in_client, monkeypatch):
    _install_audit_records(monkeypatch, [])
    _install_catalog(monkeypatch, {})
    client, _ = signed_in_client(role="contributor")
    res = client.get("/api/admin/activity")
    assert res.status_code == 403


def test_admin_feed_maintainer_redacts_actor(signed_in_client, monkeypatch):
    _install_audit_records(monkeypatch, [
        _record("reciter.marked_ready", actor_login="alice"),
    ])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})
    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M")
    res = client.get("/api/admin/activity")
    assert res.status_code == 200
    body = json.loads(res.data)
    assert len(body["cards"]) == 1
    assert "actor_login" not in body["cards"][0]


def test_admin_feed_owner_sees_actor(signed_in_client, monkeypatch):
    _install_audit_records(monkeypatch, [
        _record("reciter.marked_ready", actor_login="alice"),
    ])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})
    client, _ = signed_in_client(role="owner", hf_user_id="u-O")
    res = client.get("/api/admin/activity")
    body = json.loads(res.data)
    assert body["cards"][0]["actor_login"] == "alice"


def test_admin_feed_archived_param(signed_in_client, monkeypatch):
    """archived=true returns the caller's dismissed cards instead of live."""
    from scripts.lib.schemas import Actor, Role
    from services import activity_classification as ac
    from services import activity_state as activity_state_service

    _silence_audit(monkeypatch)
    rec = _record("reciter.marked_ready")
    _install_audit_records(monkeypatch, [rec])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    activity_state_service.dismiss(
        ac.audit_id(rec),
        actor=Actor(hf_user_id="u-M", login_at_time="mod", role=Role.MAINTAINER),
    )

    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M")
    res_live = client.get("/api/admin/activity")
    assert len(json.loads(res_live.data)["cards"]) == 0

    res_archived = client.get("/api/admin/activity?archived=true")
    assert len(json.loads(res_archived.data)["cards"]) == 1


# ---------------------------------------------------------------------------
# POST /api/admin/activity/dismiss + undismiss
# ---------------------------------------------------------------------------


def test_dismiss_requires_maintainer(signed_in_client, monkeypatch):
    _silence_audit(monkeypatch)
    client, _ = signed_in_client(role="contributor")
    res = client.post(
        "/api/admin/activity/dismiss",
        data=json.dumps({"audit_id": "abc123"}),
        headers=_HEADERS,
    )
    assert res.status_code == 403


def test_dismiss_records_per_user(signed_in_client, monkeypatch):
    from services import activity_state as activity_state_service
    _silence_audit(monkeypatch)
    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M")

    res = client.post(
        "/api/admin/activity/dismiss",
        data=json.dumps({"audit_id": "abc123"}),
        headers=_HEADERS,
    )
    assert res.status_code == 200
    assert activity_state_service.is_dismissed("abc123", "u-M") is True


def test_dismiss_missing_audit_id_returns_400(signed_in_client, monkeypatch):
    _silence_audit(monkeypatch)
    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M")
    res = client.post(
        "/api/admin/activity/dismiss",
        data=json.dumps({}),
        headers=_HEADERS,
    )
    assert res.status_code == 400


def test_dismiss_missing_origin_returns_403(signed_in_client, monkeypatch):
    _silence_audit(monkeypatch)
    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M")
    res = client.post(
        "/api/admin/activity/dismiss",
        data=json.dumps({"audit_id": "abc"}),
        headers={"Content-Type": "application/json"},  # no Origin
    )
    assert res.status_code == 403


def test_undismiss_removes_dismissal(signed_in_client, monkeypatch):
    from scripts.lib.schemas import Actor, Role
    from services import activity_state as activity_state_service
    _silence_audit(monkeypatch)
    activity_state_service.dismiss(
        "abc123",
        actor=Actor(hf_user_id="u-M", login_at_time="mod", role=Role.MAINTAINER),
    )

    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M")
    res = client.post(
        "/api/admin/activity/undismiss",
        data=json.dumps({"audit_id": "abc123"}),
        headers=_HEADERS,
    )
    assert res.status_code == 200
    assert activity_state_service.is_dismissed("abc123", "u-M") is False


# ---------------------------------------------------------------------------
# DELETE /api/public/activity/<audit_id>
# ---------------------------------------------------------------------------


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
