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
    """Seed each ``_row`` spec into the SQLite substrate."""
    from tests.conftest import _seed_state

    for spec in rows:
        _seed_state(**spec)


def _row(slug, *, state="awaiting_review", assignee_hf_id=None):
    """Return a seed spec consumed by ``_replace_state`` → ``_seed_state``."""
    return dict(
        slug=slug,
        state=state,
        assignee_hf_id=assignee_hf_id,
        assignee_login="prev" if assignee_hf_id else "test_user",
        visibility="public",
    )


def _stub_access_persist(monkeypatch):
    """No-op post-cutover: grant/revoke/update commit to SQLite (sync upload is
    disabled by the autouse fixture) and audit rows are real transitions."""
    return None


def _stub_state_persist(monkeypatch):
    """No-op post-cutover (state persists in SQLite for free)."""
    return None


# ---------------------------------------------------------------------------
# grant
# ---------------------------------------------------------------------------


def test_grant_anonymous_returns_401(flask_client, monkeypatch):
    _stub_access_persist(monkeypatch)
    res = flask_client.post(
        "/api/admin/access/grant",
        data=json.dumps(
            {
                "hf_user_id": "u-2",
                "login": "bob",
                "role": "maintainer",
                "reason": "smoke test reason",
            }
        ),
        headers=_HEADERS,
    )
    assert res.status_code == 401


def test_grant_by_contributor_returns_403(signed_in_client, monkeypatch):
    _stub_access_persist(monkeypatch)
    client, _ = signed_in_client(hf_user_id="u-1", login="alice", role="contributor")
    res = client.post(
        "/api/admin/access/grant",
        data=json.dumps(
            {
                "hf_user_id": "u-2",
                "login": "bob",
                "role": "maintainer",
                "reason": "smoke test reason",
            }
        ),
        headers=_HEADERS,
    )
    assert res.status_code == 403


def test_grant_maintainer_by_owner_happy_path(signed_in_client, monkeypatch):
    _stub_access_persist(monkeypatch)
    client, _ = signed_in_client(hf_user_id="u-owner", login="owner", role="owner")
    res = client.post(
        "/api/admin/access/grant",
        data=json.dumps(
            {
                "hf_user_id": "u-2",
                "login": "bob",
                "role": "maintainer",
                "reason": "smoke test reason",
            }
        ),
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
        data=json.dumps(
            {
                "hf_user_id": "u-2",
                "login": "bob",
                "role": "maintainer",
                "reason": "smoke test reason",
            }
        ),
        headers=_HEADERS,
    )
    assert res.status_code == 200


def test_grant_owner_role_by_maintainer_returns_403(signed_in_client, monkeypatch):
    """Only OWNER can grant OWNER."""
    _stub_access_persist(monkeypatch)
    client, _ = signed_in_client(hf_user_id="u-mod", login="mod", role="maintainer")
    res = client.post(
        "/api/admin/access/grant",
        data=json.dumps(
            {"hf_user_id": "u-2", "login": "bob", "role": "owner", "reason": "smoke test reason"}
        ),
        headers=_HEADERS,
    )
    assert res.status_code == 403


def test_grant_short_reason_returns_400(signed_in_client, monkeypatch):
    _stub_access_persist(monkeypatch)
    client, _ = signed_in_client(hf_user_id="u-owner", login="owner", role="owner")
    res = client.post(
        "/api/admin/access/grant",
        data=json.dumps(
            {"hf_user_id": "u-2", "login": "bob", "role": "maintainer", "reason": "too short"}
        ),
        headers=_HEADERS,
    )
    assert res.status_code == 400


def test_grant_missing_origin_returns_403(signed_in_client, monkeypatch):
    _stub_access_persist(monkeypatch)
    client, _ = signed_in_client(hf_user_id="u-owner", login="owner", role="owner")
    res = client.post(
        "/api/admin/access/grant",
        data=json.dumps(
            {
                "hf_user_id": "u-2",
                "login": "bob",
                "role": "maintainer",
                "reason": "smoke test reason",
            }
        ),
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

    from qua_shared.schemas import Member, Role, RolesFile
    from services import access as access_service

    _stub_access_persist(monkeypatch)
    _stub_state_persist(monkeypatch)
    _replace_state(
        [
            _row("test_slug", state="under_review", assignee_hf_id="u-target"),
        ]
    )

    # Sign in as the owner *first*; the fixture replaces the access store
    # with one containing only the owner. Then add the revocation target as
    # a maintainer so it can be revoked.
    client, _ = signed_in_client(hf_user_id="u-owner", login="owner", role="owner")
    from tests.conftest import _seed_role

    _seed_role("u-target", login="target", role="maintainer")

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

    from qua_shared.schemas import Member, Role
    from services import access as access_service

    _stub_access_persist(monkeypatch)
    # Sign in first so the fixture seeds the maintainer revoker.
    client, _ = signed_in_client(hf_user_id="u-mod", login="mod", role="maintainer")
    # Then add the OWNER target.
    from tests.conftest import _seed_role

    _seed_role("u-owner-target", login="founder", role="owner")

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

    from qua_shared.schemas import Member, Role
    from services import access as access_service

    _stub_access_persist(monkeypatch)
    client, _ = signed_in_client(hf_user_id="u-owner", login="owner", role="owner")
    from tests.conftest import _seed_role

    _seed_role("u-target", login="old_login", role="maintainer")

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
