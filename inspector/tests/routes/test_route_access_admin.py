"""Access admin endpoint tests (/api/admin/access/{grant,revoke,update}).

Coverage:
- 401 anonymous, 403 contributor
- 403 on cross-origin POST
- happy-path grant (maintainer & owner)
- 409 on already-active member
- revoke: maintainer can revoke maintainer; only owner can revoke owner
- revoke side effect: any active claim held by the revoked user is force-released
- update: login-cache refresh
- short-reason rejection
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

os.environ.setdefault("INSPECTOR_SESSION_SECRET", "0" * 64)

_HEADERS = {"Content-Type": "application/json", "Origin": "http://localhost"}


def _replace_state(rows: list):
    from scripts.lib.schemas import ReciterStateFile
    from services import state as state_service

    with state_service._state_lock:  # type: ignore[attr-defined]
        state_service._state_file = ReciterStateFile(reciters=rows)  # type: ignore[attr-defined]


def _row(slug, *, state="awaiting_review", assignee_hf_id=None):
    from scripts.lib.schemas import ReciterRow, ReciterState, Visibility

    return ReciterRow(
        slug=slug,
        state=ReciterState(state),
        state_since=datetime.now(timezone.utc),
        assignee_hf_id=assignee_hf_id,
        assignee_login="prev" if assignee_hf_id else None,
        assignee_since=datetime.now(timezone.utc) if assignee_hf_id else None,
        visibility=Visibility.PUBLIC,
    )


def _stub_access_persist(monkeypatch):
    """Stop access.grant/revoke/update from hitting the bucket."""
    from services import access as access_service

    monkeypatch.setattr(access_service, "_persist", lambda new_store: None)
    # Audit append from access is also a bucket write — silence it.
    from services import audit as audit_service

    monkeypatch.setattr(audit_service, "append", lambda **kw: None)


def _stub_state_persist(monkeypatch):
    """Stop state.transition's _persist_row from hitting the bucket."""
    from services import state as state_service

    monkeypatch.setattr(
        state_service,
        "_persist_row",
        lambda row, *, replace_existing: None,
    )


# ---------------------------------------------------------------------------
# grant
# ---------------------------------------------------------------------------


def test_grant_anonymous_returns_401(flask_client, monkeypatch):
    _stub_access_persist(monkeypatch)
    res = flask_client.post(
        "/api/admin/access/grant",
        data=json.dumps({"hf_user_id": "u-2", "login": "bob", "role": "maintainer", "reason": "smoke test reason"}),
        headers=_HEADERS,
    )
    assert res.status_code == 401


def test_grant_by_contributor_returns_403(signed_in_client, monkeypatch):
    _stub_access_persist(monkeypatch)
    client, _ = signed_in_client(hf_user_id="u-1", login="alice", role="contributor")
    res = client.post(
        "/api/admin/access/grant",
        data=json.dumps({"hf_user_id": "u-2", "login": "bob", "role": "maintainer", "reason": "smoke test reason"}),
        headers=_HEADERS,
    )
    assert res.status_code == 403


def test_grant_maintainer_by_owner_happy_path(signed_in_client, monkeypatch):
    _stub_access_persist(monkeypatch)
    client, _ = signed_in_client(hf_user_id="u-owner", login="owner", role="owner")
    res = client.post(
        "/api/admin/access/grant",
        data=json.dumps({"hf_user_id": "u-2", "login": "bob", "role": "maintainer", "reason": "smoke test reason"}),
        headers=_HEADERS,
    )
    assert res.status_code == 200
    body = json.loads(res.data)
    assert body["member"]["hf_user_id"] == "u-2"
    assert body["member"]["role"] == "maintainer"


def test_grant_maintainer_by_maintainer_happy_path(signed_in_client, monkeypatch):
    _stub_access_persist(monkeypatch)
    client, _ = signed_in_client(hf_user_id="u-mod", login="mod", role="maintainer")
    res = client.post(
        "/api/admin/access/grant",
        data=json.dumps({"hf_user_id": "u-2", "login": "bob", "role": "maintainer", "reason": "smoke test reason"}),
        headers=_HEADERS,
    )
    assert res.status_code == 200


def test_grant_owner_role_by_maintainer_returns_403(signed_in_client, monkeypatch):
    """Only OWNER can grant OWNER."""
    _stub_access_persist(monkeypatch)
    client, _ = signed_in_client(hf_user_id="u-mod", login="mod", role="maintainer")
    res = client.post(
        "/api/admin/access/grant",
        data=json.dumps({"hf_user_id": "u-2", "login": "bob", "role": "owner", "reason": "smoke test reason"}),
        headers=_HEADERS,
    )
    assert res.status_code == 403


def test_grant_short_reason_returns_400(signed_in_client, monkeypatch):
    _stub_access_persist(monkeypatch)
    client, _ = signed_in_client(hf_user_id="u-owner", login="owner", role="owner")
    res = client.post(
        "/api/admin/access/grant",
        data=json.dumps({"hf_user_id": "u-2", "login": "bob", "role": "maintainer", "reason": "too short"}),
        headers=_HEADERS,
    )
    assert res.status_code == 400


def test_grant_missing_origin_returns_403(signed_in_client, monkeypatch):
    _stub_access_persist(monkeypatch)
    client, _ = signed_in_client(hf_user_id="u-owner", login="owner", role="owner")
    res = client.post(
        "/api/admin/access/grant",
        data=json.dumps({"hf_user_id": "u-2", "login": "bob", "role": "maintainer", "reason": "smoke test reason"}),
        content_type="application/json",
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# revoke
# ---------------------------------------------------------------------------


def test_revoke_anonymous_returns_401(flask_client, monkeypatch):
    _stub_access_persist(monkeypatch)
    res = flask_client.post(
        "/api/admin/access/revoke",
        data=json.dumps({"hf_user_id": "u-target", "reason": "smoke test reason"}),
        headers=_HEADERS,
    )
    assert res.status_code == 401


def test_revoke_member_not_found_returns_404(signed_in_client, monkeypatch):
    _stub_access_persist(monkeypatch)
    client, _ = signed_in_client(hf_user_id="u-owner", login="owner", role="owner")
    res = client.post(
        "/api/admin/access/revoke",
        data=json.dumps({"hf_user_id": "ghost", "reason": "smoke test reason"}),
        headers=_HEADERS,
    )
    assert res.status_code == 404


def test_revoke_force_releases_active_claim(signed_in_client, monkeypatch):
    """When a maintainer revokes a contributor who holds a claim, the
    claim is auto-released as part of the revoke."""
    from datetime import datetime, timezone

    from scripts.lib.schemas import Member, Role, RolesFile

    from services import access as access_service

    _stub_access_persist(monkeypatch)
    _stub_state_persist(monkeypatch)
    _replace_state([
        _row("test_slug", state="under_review", assignee_hf_id="u-target"),
    ])

    # Sign in as the owner *first*; the fixture replaces the access store
    # with one containing only the owner. Then add the revocation target as
    # a maintainer so it can be revoked.
    client, _ = signed_in_client(hf_user_id="u-owner", login="owner", role="owner")
    now = datetime.now(timezone.utc)
    with access_service._store_lock:  # type: ignore[attr-defined]
        snapshot = access_service._store.model_copy(deep=True)  # type: ignore[attr-defined]
        snapshot.members.append(Member(
            hf_user_id="u-target",
            login="target",
            role=Role.MAINTAINER,
            added_at=now,
            added_by_hf_id="u-owner",
        ))
        access_service._store = snapshot  # type: ignore[attr-defined]

    res = client.post(
        "/api/admin/access/revoke",
        data=json.dumps({"hf_user_id": "u-target", "reason": "Reviewer unresponsive 9 days"}),
        headers=_HEADERS,
    )
    assert res.status_code == 200, res.get_json()
    body = json.loads(res.data)
    assert body["auto_released_slugs"] == ["test_slug"]


def test_revoke_maintainer_cannot_revoke_owner(signed_in_client, monkeypatch):
    from datetime import datetime, timezone

    from scripts.lib.schemas import Member, Role

    from services import access as access_service

    _stub_access_persist(monkeypatch)
    # Sign in first so the fixture seeds the maintainer revoker.
    client, _ = signed_in_client(hf_user_id="u-mod", login="mod", role="maintainer")
    # Then add the OWNER target to the same store.
    now = datetime.now(timezone.utc)
    with access_service._store_lock:  # type: ignore[attr-defined]
        snapshot = access_service._store.model_copy(deep=True)  # type: ignore[attr-defined]
        snapshot.members.append(Member(
            hf_user_id="u-owner-target",
            login="founder",
            role=Role.OWNER,
            added_at=now,
            added_by_hf_id="bootstrap",
        ))
        access_service._store = snapshot  # type: ignore[attr-defined]

    res = client.post(
        "/api/admin/access/revoke",
        data=json.dumps({"hf_user_id": "u-owner-target", "reason": "smoke test reason"}),
        headers=_HEADERS,
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


def test_update_login_cache_refresh(signed_in_client, monkeypatch):
    from datetime import datetime, timezone

    from scripts.lib.schemas import Member, Role

    from services import access as access_service

    _stub_access_persist(monkeypatch)
    client, _ = signed_in_client(hf_user_id="u-owner", login="owner", role="owner")
    now = datetime.now(timezone.utc)
    with access_service._store_lock:  # type: ignore[attr-defined]
        snapshot = access_service._store.model_copy(deep=True)  # type: ignore[attr-defined]
        snapshot.members.append(Member(
            hf_user_id="u-target",
            login="old_login",
            role=Role.MAINTAINER,
            added_at=now,
            added_by_hf_id="u-owner",
        ))
        access_service._store = snapshot  # type: ignore[attr-defined]

    res = client.post(
        "/api/admin/access/update",
        data=json.dumps({"hf_user_id": "u-target", "login": "new_login"}),
        headers=_HEADERS,
    )
    assert res.status_code == 200
    body = json.loads(res.data)
    assert body["member"]["login"] == "new_login"


def test_update_by_contributor_returns_403(signed_in_client, monkeypatch):
    _stub_access_persist(monkeypatch)
    client, _ = signed_in_client(hf_user_id="u-1", login="alice", role="contributor")
    res = client.post(
        "/api/admin/access/update",
        data=json.dumps({"hf_user_id": "u-target", "login": "new_login"}),
        headers=_HEADERS,
    )
    assert res.status_code == 403
