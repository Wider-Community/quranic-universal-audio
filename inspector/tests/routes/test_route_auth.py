"""HF OAuth + identity session route tests.

Coverage:
- ``/api/me`` anonymous shape
- ``/api/me`` signed-in identity + active_claim
- ``/api/me`` role refresh after access revoke (no re-login needed)
- ``/api/auth/logout`` clears cookie
- ``/api/auth/login`` redirects when OAuth not configured (503)

OAuth callback exchange is integration-shaped (authorizes against HF) and is
covered by manual smoke during deploy rather than a mocked unit test.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

# Ensure session secret is set before app import — auth.py reads it via the
# secrets_guard module on first use.
os.environ.setdefault("INSPECTOR_SESSION_SECRET", "0" * 64)


def _seed_state_row(slug: str, *, assignee_hf_id: str | None = None,
                    state: str = "awaiting_review"):
    """Replace the in-memory state store with a single row for ``slug``."""
    from scripts.lib.schemas import ReciterRow, ReciterState, ReciterStateFile, Visibility

    from services import state as state_service

    row = ReciterRow(
        slug=slug,
        state=ReciterState(state),
        state_since=datetime.now(timezone.utc),
        assignee_hf_id=assignee_hf_id,
        assignee_login="someone" if assignee_hf_id else None,
        assignee_since=datetime.now(timezone.utc) if assignee_hf_id else None,
        visibility=Visibility.PUBLIC,
    )
    new_file = ReciterStateFile(reciters=[row])
    with state_service._state_lock:  # type: ignore[attr-defined]
        state_service._state_file = new_file  # type: ignore[attr-defined]


def _clear_state():
    from scripts.lib.schemas import ReciterStateFile
    from services import state as state_service

    with state_service._state_lock:  # type: ignore[attr-defined]
        state_service._state_file = ReciterStateFile()  # type: ignore[attr-defined]


def test_me_anonymous_returns_null_shape(flask_client):
    """Anonymous /api/me returns a uniform null-filled shape so the SPA can
    consume the same schema regardless of auth state."""
    _clear_state()
    resp = flask_client.get("/api/me")
    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body == {
        "login": None,
        "hf_user_id": None,
        "role": None,
        "active_claim": None,
        "dev_mode": False,
    }


def test_me_signed_in_returns_identity(signed_in_client):
    """Signed-in /api/me returns the identity + active_claim (null when no claim)."""
    _clear_state()
    client, user = signed_in_client(hf_user_id="u-1", login="alice", role="contributor")
    resp = client.get("/api/me")
    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body["hf_user_id"] == "u-1"
    assert body["login"] == "alice"
    assert body["role"] == "contributor"
    assert body["active_claim"] is None


def test_me_active_claim_reflects_held_under_review(signed_in_client):
    """When the signed-in user is the assignee of an under_review row,
    /api/me surfaces it under active_claim."""
    _seed_state_row("test_slug", assignee_hf_id="u-2", state="under_review")
    client, user = signed_in_client(hf_user_id="u-2", login="bob", role="contributor")
    resp = client.get("/api/me")
    assert resp.status_code == 200
    assert json.loads(resp.data)["active_claim"] == "test_slug"


def test_me_role_reflects_live_access_revoke(signed_in_client):
    """Revoke a maintainer's role mid-session → next /api/me returns
    role=contributor without re-login. Validates that role is resolved
    fresh per request and not pinned in the cookie."""
    from scripts.lib.schemas import RolesFile

    from services import access as access_service

    _clear_state()
    # Sign in as maintainer.
    client, user = signed_in_client(hf_user_id="u-3", login="carol", role="maintainer")

    # Confirm /api/me reflects the maintainer role.
    resp1 = client.get("/api/me")
    assert json.loads(resp1.data)["role"] == "maintainer"

    # Revoke (drop the member from the in-memory store).
    with access_service._store_lock:  # type: ignore[attr-defined]
        access_service._store = RolesFile()  # type: ignore[attr-defined]

    # Same cookie, same client — but role resolution is live.
    resp2 = client.get("/api/me")
    assert json.loads(resp2.data)["role"] == "contributor"


def test_logout_clears_cookie(signed_in_client):
    """POST /api/auth/logout returns 200 and emits a Set-Cookie that expires
    the identity cookie. The user's claim is NOT released by logout."""
    client, user = signed_in_client(hf_user_id="u-4", login="dave")
    resp = client.post(
        "/api/auth/logout",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 200
    cookies = resp.headers.getlist("Set-Cookie")
    assert any("inspector_session=" in c and "Max-Age=0" in c for c in cookies)


def test_logout_no_session_still_200(flask_client):
    """Logout is idempotent on an anonymous client."""
    resp = flask_client.post(
        "/api/auth/logout",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 200


def test_login_503_when_oauth_unconfigured(flask_client, monkeypatch):
    """With OAUTH_CLIENT_ID unset, /api/auth/login returns 503."""
    monkeypatch.delenv("OAUTH_CLIENT_ID", raising=False)
    resp = flask_client.get("/api/auth/login")
    assert resp.status_code == 503
    assert json.loads(resp.data)["error"]


def test_me_with_tampered_cookie_returns_anonymous(flask_client):
    """A cookie with an invalid signature decodes to None → anonymous shape."""
    flask_client.set_cookie("inspector_session", "tampered.payload.sig", path="/")
    resp = flask_client.get("/api/me")
    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body["hf_user_id"] is None
