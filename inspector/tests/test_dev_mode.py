"""Dev-mode auth bypass + /api/dev/role route tests.

Covers:
- ``current_user()`` in dev mode reads the ``inspector_dev_role`` cookie,
  defaults to owner, and yields ``None`` for ``"anonymous"``.
- Garbage cookie values fall back to owner (no 500).
- ``/api/me`` exposes ``dev_mode`` flag in both branches.
- ``/api/dev/role`` 404s when dev mode is off, 200/400 when on; sets the cookie.
- The default test run leaves dev mode off so existing fixtures behave
  exactly as before.

The dev blueprint is registered unconditionally in ``routes/__init__.py``;
its handler ``abort(404)``s when dev mode is off. Tests flip
``INSPECTOR_DEV_MODE`` via ``monkeypatch.setenv`` to toggle behaviour.
"""

from __future__ import annotations

import json
import os

import pytest

# Ensure session secret is set before app import.
os.environ.setdefault("INSPECTOR_SESSION_SECRET", "0" * 64)


@pytest.fixture
def dev_mode_client(monkeypatch):
    """Flask client with ``INSPECTOR_DEV_MODE=1`` for the duration of the test."""
    monkeypatch.setenv("INSPECTOR_DEV_MODE", "1")

    from app import app

    # State starts empty via the autouse _substrate_db fixture.
    app.config["TESTING"] = True
    return app.test_client()


# ---- current_user() dev-mode branch ----


def test_dev_mode_off_by_default_in_pytest(flask_client):
    """app.py auto-enable must skip pytest. /api/me reports dev_mode=False."""
    # Be defensive: explicitly drop the env var in case some other test set it.
    os.environ.pop("INSPECTOR_DEV_MODE", None)
    resp = flask_client.get("/api/me")
    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body["dev_mode"] is False
    assert body["hf_user_id"] is None  # no cookie → anonymous in prod path


def test_dev_mode_default_owner_when_cookie_missing(dev_mode_client):
    """No cookie → synthetic dev user with role=owner."""
    resp = dev_mode_client.get("/api/me")
    assert resp.status_code == 200
    body = json.loads(resp.data)
    caps = body.pop("capabilities")
    assert body == {
        "login": "dev-owner",
        "hf_user_id": "dev-owner",
        "role": "owner",
        "active_claim": None,
        "active_claims": [],
        "dev_mode": True,
        "guides_read": [],
    }
    # Owner is a superuser → holds every registered capability.
    from qua_shared.schemas import CAPABILITIES

    assert set(caps) == {c.id for c in CAPABILITIES}


@pytest.mark.parametrize("role", ["owner", "maintainer", "contributor"])
def test_dev_mode_cookie_drives_role(dev_mode_client, role):
    """The inspector_dev_role cookie sets the synthetic user's role."""
    dev_mode_client.set_cookie("inspector_dev_role", role, path="/")
    resp = dev_mode_client.get("/api/me")
    body = json.loads(resp.data)
    assert body["role"] == role
    assert body["hf_user_id"] == f"dev-{role}"
    assert body["dev_mode"] is True


def test_dev_mode_anonymous_cookie_yields_null_user(dev_mode_client):
    """Cookie value 'anonymous' makes current_user() return None — the
    /api/me shape mirrors a signed-out user, but with dev_mode=True so
    the frontend still renders the role switcher."""
    dev_mode_client.set_cookie("inspector_dev_role", "anonymous", path="/")
    resp = dev_mode_client.get("/api/me")
    body = json.loads(resp.data)
    assert body == {
        "login": None,
        "hf_user_id": None,
        "role": None,
        "active_claim": None,
        "active_claims": [],
        "dev_mode": True,
        "capabilities": ["view.catalog", "view.public_activity"],
        "guides_read": [],
    }


def test_dev_mode_garbage_cookie_falls_back_to_owner(dev_mode_client):
    """A cookie value that's not a known Role must NOT 500 the dev page."""
    dev_mode_client.set_cookie("inspector_dev_role", "hacker", path="/")
    resp = dev_mode_client.get("/api/me")
    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body["role"] == "owner"


def test_dev_mode_ignores_real_oauth_cookie(dev_mode_client):
    """When dev mode is on, a forged inspector_session cookie must not
    promote the user past the synthetic identity — the bypass is total."""
    from services import auth as auth_service

    real_cookie = auth_service.encode_session(login="real_user", hf_user_id="real-id")
    dev_mode_client.set_cookie(auth_service.SESSION_COOKIE_NAME, real_cookie, path="/")
    resp = dev_mode_client.get("/api/me")
    body = json.loads(resp.data)
    assert body["hf_user_id"] == "dev-owner"
    assert body["login"] == "dev-owner"


# ---- /api/dev/role route ----


def test_dev_role_route_404_in_prod(flask_client):
    """In prod the dev blueprint is not registered. Route must 404."""
    os.environ.pop("INSPECTOR_DEV_MODE", None)
    resp = flask_client.post(
        "/api/dev/role",
        json={"role": "owner"},
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 404


def test_dev_role_route_sets_cookie(dev_mode_client):
    """POST /api/dev/role with a valid role returns 200 and sets the cookie."""
    resp = dev_mode_client.post(
        "/api/dev/role",
        json={"role": "maintainer"},
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body == {"ok": True, "role": "maintainer"}
    cookies = resp.headers.getlist("Set-Cookie")
    assert any("inspector_dev_role=maintainer" in c for c in cookies)
    assert any("HttpOnly" in c for c in cookies if "inspector_dev_role=" in c)


def test_dev_role_route_rejects_unknown_role(dev_mode_client):
    """Body with an unknown role string → 400 with allowed list."""
    resp = dev_mode_client.post(
        "/api/dev/role",
        json={"role": "superuser"},
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 400
    body = json.loads(resp.data)
    assert body["error"]
    assert set(body["allowed"]) == {"owner", "maintainer", "contributor", "anonymous"}


def test_dev_role_route_requires_same_origin(dev_mode_client):
    """The same-origin decorator must still gate the dev route."""
    resp = dev_mode_client.post("/api/dev/role", json={"role": "owner"})
    assert resp.status_code == 403


def test_dev_role_anonymous_then_me_round_trip(dev_mode_client):
    """Switch to anonymous via the route, then verify /api/me reflects it."""
    r1 = dev_mode_client.post(
        "/api/dev/role",
        json={"role": "anonymous"},
        headers={"Origin": "http://localhost"},
    )
    assert r1.status_code == 200
    r2 = dev_mode_client.get("/api/me")
    body = json.loads(r2.data)
    assert body["hf_user_id"] is None
    assert body["dev_mode"] is True


# ---- Existing fixture parity ----


def test_signed_in_client_fixture_unaffected_in_prod(signed_in_client):
    """The signed_in_client fixture must continue to authenticate via the
    real OAuth-cookie path when dev mode is off (the default during tests)."""
    os.environ.pop("INSPECTOR_DEV_MODE", None)
    client, user = signed_in_client(hf_user_id="u-fix", login="fix_user", role="maintainer")
    resp = client.get("/api/me")
    body = json.loads(resp.data)
    assert body["hf_user_id"] == "u-fix"
    assert body["role"] == "maintainer"
    assert body["dev_mode"] is False


# ---- Behind-proxy hard guard (deployed-Space safety net) ----


def test_is_dev_mode_false_behind_proxy(monkeypatch):
    """Even with INSPECTOR_DEV_MODE=1, the bypass is structurally OFF behind the
    deployed reverse proxy — a stray dev-mode env var on a Space can never
    activate the synthetic-owner bypass."""
    from services import auth as auth_service

    monkeypatch.setenv("INSPECTOR_DEV_MODE", "1")
    monkeypatch.setenv("INSPECTOR_BEHIND_PROXY", "1")
    assert auth_service.is_dev_mode() is False


def test_is_dev_mode_true_without_proxy(monkeypatch):
    """The bypass stays available for local dev (no proxy)."""
    from services import auth as auth_service

    monkeypatch.setenv("INSPECTOR_DEV_MODE", "1")
    monkeypatch.delenv("INSPECTOR_BEHIND_PROXY", raising=False)
    assert auth_service.is_dev_mode() is True


def test_dev_bypass_inactive_behind_proxy(dev_mode_client, monkeypatch):
    """With both flags set, /api/me falls back to the real OAuth path: an
    anonymous caller stays anonymous instead of becoming a synthetic owner."""
    monkeypatch.setenv("INSPECTOR_BEHIND_PROXY", "1")
    resp = dev_mode_client.get("/api/me")
    body = json.loads(resp.data)
    assert body["dev_mode"] is False
    assert body["hf_user_id"] is None


def test_assert_dev_mode_safe_aborts_on_proxy_plus_devmode(monkeypatch):
    """Boot guard: dev-mode + behind-proxy together is a hard RuntimeError."""
    from services import auth as auth_service

    monkeypatch.setenv("INSPECTOR_DEV_MODE", "1")
    monkeypatch.setenv("INSPECTOR_BEHIND_PROXY", "1")
    with pytest.raises(RuntimeError, match="never run on a deployed Space"):
        auth_service.assert_dev_mode_safe()


@pytest.mark.parametrize("dev,proxy", [("1", None), ("0", "1"), (None, "1"), (None, None)])
def test_assert_dev_mode_safe_allows_valid_combos(monkeypatch, dev, proxy):
    """The boot guard does not fire for any legitimate combination."""
    from services import auth as auth_service

    if dev is None:
        monkeypatch.delenv("INSPECTOR_DEV_MODE", raising=False)
    else:
        monkeypatch.setenv("INSPECTOR_DEV_MODE", dev)
    if proxy is None:
        monkeypatch.delenv("INSPECTOR_BEHIND_PROXY", raising=False)
    else:
        monkeypatch.setenv("INSPECTOR_BEHIND_PROXY", proxy)
    auth_service.assert_dev_mode_safe()  # must not raise
