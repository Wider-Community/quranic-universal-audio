"""Admin override endpoint tests (Phase 4).

Covers /api/admin/{claim/force-release, claim/reassign, state/force-set,
send-back, users/lookup}. Mirrors test_route_access_admin.py patterns:
in-memory state replacement + persistence stubs to avoid the bucket.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

os.environ.setdefault("INSPECTOR_SESSION_SECRET", "0" * 64)

_HEADERS = {"Content-Type": "application/json", "Origin": "http://localhost"}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _replace_state(rows: list):
    """Seed each ``_row`` spec into the SQLite substrate (post-cutover source
    of truth; the in-memory ``_state_file`` is gone)."""
    from tests.conftest import _seed_state

    for spec in rows:
        _seed_state(**spec)


def _row(
    slug,
    *,
    state="under_review",
    assignee_hf_id="u-target",
    assignee_login="target_user",
    marked_ready=False,
):
    """Return a seed spec consumed by ``_replace_state`` → ``_seed_state``."""
    return dict(
        slug=slug,
        state=state,
        assignee_hf_id=assignee_hf_id,
        assignee_login=assignee_login,
        marked_ready=marked_ready,
        visibility="public",
    )


def _stub_state_persist(monkeypatch):
    """No-op post-cutover: state persists in SQLite for free and audit rows are
    real transition rows. Kept so call sites don't churn."""
    return None


def _stub_hf_users(monkeypatch, *, returns):
    """Stub hf_users.lookup. ``returns`` is the value to return (HfUser or None)
    or a callable taking ``login`` and returning either.
    """
    from services import hf_users

    if callable(returns):
        monkeypatch.setattr(hf_users, "lookup", returns)
    else:
        monkeypatch.setattr(hf_users, "lookup", lambda login: returns)


def _hf_user(hf_user_id="u-new", login="new_user", fullname="New User"):
    from services.hf_users import HfUser

    return HfUser(
        hf_user_id=hf_user_id,
        login=login,
        fullname=fullname,
        avatar_url=f"https://huggingface.co/avatars/{login}.png",
    )


# ---------------------------------------------------------------------------
# force-release
# ---------------------------------------------------------------------------


def test_force_release_anonymous_returns_401(flask_client):
    res = flask_client.post(
        "/api/admin/claim/force-release/test_slug",
        data=json.dumps({"reason": "Reviewer disappeared 9 days ago."}),
        headers=_HEADERS,
    )
    assert res.status_code == 401


def test_force_release_by_contributor_returns_403(signed_in_client):
    client, _ = signed_in_client(role="contributor")
    res = client.post(
        "/api/admin/claim/force-release/test_slug",
        data=json.dumps({"reason": "Reviewer disappeared 9 days ago."}),
        headers=_HEADERS,
    )
    assert res.status_code == 403


def test_force_release_happy_path(signed_in_client, monkeypatch):
    _stub_state_persist(monkeypatch)
    _replace_state([_row("test_slug")])
    client, _ = signed_in_client(role="maintainer", hf_user_id="u-mod", login="mod")

    res = client.post(
        "/api/admin/claim/force-release/test_slug",
        data=json.dumps({"reason": "Reviewer disappeared 9 days ago."}),
        headers=_HEADERS,
    )
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["row"]["state"] == "awaiting_review"
    assert body["row"]["assignee_hf_id"] is None
    assert body["original_assignee_hf_id"] == "u-target"


def test_force_release_short_reason_returns_400(signed_in_client, monkeypatch):
    _stub_state_persist(monkeypatch)
    _replace_state([_row("test_slug")])
    client, _ = signed_in_client(role="maintainer")
    res = client.post(
        "/api/admin/claim/force-release/test_slug",
        data=json.dumps({"reason": "too short"}),
        headers=_HEADERS,
    )
    assert res.status_code == 400


def test_force_release_wrong_state_returns_400(signed_in_client, monkeypatch):
    _stub_state_persist(monkeypatch)
    _replace_state([_row("test_slug", state="awaiting_review", assignee_hf_id=None)])
    client, _ = signed_in_client(role="maintainer")
    res = client.post(
        "/api/admin/claim/force-release/test_slug",
        data=json.dumps({"reason": "Trying to release the wrong state."}),
        headers=_HEADERS,
    )
    assert res.status_code == 400


def test_force_release_missing_origin_returns_403(signed_in_client, monkeypatch):
    _stub_state_persist(monkeypatch)
    _replace_state([_row("test_slug")])
    client, _ = signed_in_client(role="maintainer")
    res = client.post(
        "/api/admin/claim/force-release/test_slug",
        data=json.dumps({"reason": "Reviewer disappeared 9 days ago."}),
        content_type="application/json",
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# reassign
# ---------------------------------------------------------------------------


def test_reassign_happy_path(signed_in_client, monkeypatch):
    _stub_state_persist(monkeypatch)
    _stub_hf_users(monkeypatch, returns=_hf_user(hf_user_id="u-new", login="NewUser"))
    _replace_state([_row("test_slug")])
    client, _ = signed_in_client(role="maintainer")

    res = client.post(
        "/api/admin/claim/reassign/test_slug",
        data=json.dumps({"to_login": "newuser", "reason": "Hand-off to NewUser."}),
        headers=_HEADERS,
    )
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["row"]["assignee_hf_id"] == "u-new"
    assert body["row"]["assignee_login"] == "NewUser"
    assert body["to_user"]["hf_user_id"] == "u-new"


def test_reassign_unknown_login_returns_400(signed_in_client, monkeypatch):
    _stub_state_persist(monkeypatch)
    _stub_hf_users(monkeypatch, returns=None)
    _replace_state([_row("test_slug")])
    client, _ = signed_in_client(role="maintainer")

    res = client.post(
        "/api/admin/claim/reassign/test_slug",
        data=json.dumps({"to_login": "ghost", "reason": "Hand-off to ghost user."}),
        headers=_HEADERS,
    )
    assert res.status_code == 400
    body = res.get_json()
    assert body["unknown_login"] == "ghost"


def test_reassign_hf_outage_returns_502(signed_in_client, monkeypatch):
    from services import hf_users

    _stub_state_persist(monkeypatch)
    _replace_state([_row("test_slug")])

    def _raise(login):
        raise hf_users.HfUserLookupError("network down")

    monkeypatch.setattr(hf_users, "lookup", _raise)
    client, _ = signed_in_client(role="maintainer")

    res = client.post(
        "/api/admin/claim/reassign/test_slug",
        data=json.dumps({"to_login": "alice", "reason": "Hand-off attempt."}),
        headers=_HEADERS,
    )
    assert res.status_code == 502


def test_reassign_to_same_assignee_returns_400(signed_in_client, monkeypatch):
    _stub_state_persist(monkeypatch)
    _stub_hf_users(monkeypatch, returns=_hf_user(hf_user_id="u-target", login="target_user"))
    _replace_state([_row("test_slug")])
    client, _ = signed_in_client(role="maintainer")

    res = client.post(
        "/api/admin/claim/reassign/test_slug",
        data=json.dumps({
            "to_login": "target_user",
            "reason": "Trying to reassign to same user.",
        }),
        headers=_HEADERS,
    )
    assert res.status_code == 400


def test_reassign_missing_to_login_returns_400(signed_in_client, monkeypatch):
    _stub_state_persist(monkeypatch)
    _replace_state([_row("test_slug")])
    client, _ = signed_in_client(role="maintainer")

    res = client.post(
        "/api/admin/claim/reassign/test_slug",
        data=json.dumps({"reason": "Missing to_login field test."}),
        headers=_HEADERS,
    )
    assert res.status_code == 400


def test_reassign_short_reason_returns_400(signed_in_client, monkeypatch):
    _stub_state_persist(monkeypatch)
    _stub_hf_users(monkeypatch, returns=_hf_user())
    _replace_state([_row("test_slug")])
    client, _ = signed_in_client(role="maintainer")

    res = client.post(
        "/api/admin/claim/reassign/test_slug",
        data=json.dumps({"to_login": "alice", "reason": "short"}),
        headers=_HEADERS,
    )
    assert res.status_code == 400


def test_reassign_by_contributor_returns_403(signed_in_client):
    client, _ = signed_in_client(role="contributor")
    res = client.post(
        "/api/admin/claim/reassign/test_slug",
        data=json.dumps({"to_login": "alice", "reason": "Hand-off attempt."}),
        headers=_HEADERS,
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# send-back
# ---------------------------------------------------------------------------


def test_send_back_happy_path(signed_in_client, monkeypatch):
    _stub_state_persist(monkeypatch)
    _replace_state([_row("test_slug", marked_ready=True)])
    client, _ = signed_in_client(role="maintainer")

    res = client.post(
        "/api/admin/send-back/test_slug",
        data=json.dumps({"reason": "Needs more QC passes — missing words check failing."}),
        headers=_HEADERS,
    )
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["row"]["marked_ready"] is False
    assert body["row"]["state"] == "under_review"
    assert body["row"]["assignee_hf_id"] == "u-target"  # retained


def test_send_back_not_marked_ready_returns_400(signed_in_client, monkeypatch):
    _stub_state_persist(monkeypatch)
    _replace_state([_row("test_slug", marked_ready=False)])
    client, _ = signed_in_client(role="maintainer")

    res = client.post(
        "/api/admin/send-back/test_slug",
        data=json.dumps({"reason": "Cannot send back; not marked ready."}),
        headers=_HEADERS,
    )
    assert res.status_code == 400


def test_send_back_by_contributor_returns_403(signed_in_client):
    client, _ = signed_in_client(role="contributor")
    res = client.post(
        "/api/admin/send-back/test_slug",
        data=json.dumps({"reason": "Should be blocked by RBAC."}),
        headers=_HEADERS,
    )
    assert res.status_code == 403


def test_send_back_short_reason_returns_400(signed_in_client, monkeypatch):
    _stub_state_persist(monkeypatch)
    _replace_state([_row("test_slug", marked_ready=True)])
    client, _ = signed_in_client(role="maintainer")

    res = client.post(
        "/api/admin/send-back/test_slug",
        data=json.dumps({"reason": "too short"}),
        headers=_HEADERS,
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# users/lookup
# ---------------------------------------------------------------------------


def test_users_lookup_happy_path(signed_in_client, monkeypatch):
    _stub_hf_users(monkeypatch, returns=_hf_user(login="Alice", fullname="Alice X"))
    client, _ = signed_in_client(role="maintainer")

    res = client.post(
        "/api/admin/users/lookup",
        data=json.dumps({"login": "alice"}),
        headers=_HEADERS,
    )
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["login"] == "Alice"
    assert body["fullname"] == "Alice X"


def test_users_lookup_unknown_returns_404(signed_in_client, monkeypatch):
    _stub_hf_users(monkeypatch, returns=None)
    client, _ = signed_in_client(role="maintainer")

    res = client.post(
        "/api/admin/users/lookup",
        data=json.dumps({"login": "ghost"}),
        headers=_HEADERS,
    )
    assert res.status_code == 404


def test_users_lookup_hf_outage_returns_502(signed_in_client, monkeypatch):
    from services import hf_users

    def _raise(login):
        raise hf_users.HfUserLookupError("network down")

    monkeypatch.setattr(hf_users, "lookup", _raise)
    client, _ = signed_in_client(role="maintainer")

    res = client.post(
        "/api/admin/users/lookup",
        data=json.dumps({"login": "alice"}),
        headers=_HEADERS,
    )
    assert res.status_code == 502


def test_users_lookup_missing_login_returns_400(signed_in_client, monkeypatch):
    client, _ = signed_in_client(role="maintainer")
    res = client.post(
        "/api/admin/users/lookup",
        data=json.dumps({}),
        headers=_HEADERS,
    )
    assert res.status_code == 400


def test_users_lookup_by_contributor_returns_403(signed_in_client):
    client, _ = signed_in_client(role="contributor")
    res = client.post(
        "/api/admin/users/lookup",
        data=json.dumps({"login": "alice"}),
        headers=_HEADERS,
    )
    assert res.status_code == 403


def test_users_lookup_anonymous_returns_401(flask_client):
    res = flask_client.post(
        "/api/admin/users/lookup",
        data=json.dumps({"login": "alice"}),
        headers=_HEADERS,
    )
    assert res.status_code == 401
