"""HF OAuth + signed-cookie session.

Two cookie surfaces:
- Flask's default ``session`` cookie (signed via ``app.secret_key``) is the
  short-lived OAuth-state store between ``/authorize`` and ``/callback``
  (~30 s lifetime). Authlib uses this internally.
- ``inspector_session`` cookie signed via ``itsdangerous`` is the long-lived
  (1 week) identity cookie, set after a successful callback. Holds
  ``{login, hf_user_id, iat}``.

The identity cookie does NOT carry ``role`` — ``current_user()`` resolves
role fresh on every call via ``access.resolve_role``, so a revoked
maintainer becomes a contributor on the very next request without re-login.
CSRF defense for mutating routes is ``SameSite=Lax`` + ``require_same_origin``.

Local dev (``INSPECTOR_DEV_MODE=1``) bypasses OAuth entirely: ``current_user()``
returns a synthetic ``User(hf_user_id="dev-local", login="dev", role=<from cookie>)``
driven by the ``inspector_dev_role`` cookie (default ``"owner"``). Claims and
audit entries created in dev mode carry that synthetic ID — fine because dev
runs against a dev bucket. ``INSPECTOR_DEV_MODE`` is auto-enabled by ``app.py``
when running locally (no ``INSPECTOR_BEHIND_PROXY=1``, no pytest). HF Space
deploys leave it off and OAuth gates everything as before.

Spec: docs/planning/inspector-deploy/v2/phases/03-auth-and-claims.md
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from authlib.integrations.flask_client import OAuth
from flask import request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from scripts.lib.schemas import Role

from . import access
from .secrets_guard import MissingSecret, get_session_secret

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "inspector_session"
SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 1 week — mirrors hf_oauth_expiration_minutes: 10080
SESSION_SALT = "inspector-session-v1"

# Dev-mode synthetic identity. Unsigned cookie; only honoured when
# INSPECTOR_DEV_MODE=1. See module docstring.
#
# Each dev role resolves to a *distinct* synthetic identity (e.g. owner →
# ``dev-owner`` / ``@dev-owner``) so the role switcher behaves like switching
# between real HF users in prod: per-user dismissals, claims, and audit
# actor records are scoped per role rather than collapsing onto one shared
# ``dev-local`` user. ``DEV_USER_HF_ID`` is kept as the legacy default for
# any caller that still references it (no in-tree callers do).
DEV_ROLE_COOKIE_NAME = "inspector_dev_role"
DEV_USER_HF_ID = "dev-local"
DEV_USER_LOGIN = "dev"
DEV_ROLE_VALUES = ("owner", "maintainer", "contributor", "anonymous")

_oauth: OAuth | None = None


def init_oauth(app) -> OAuth:
    """Register the HF OAuth provider on the Flask app. Idempotent."""
    global _oauth
    if _oauth is not None:
        return _oauth
    oauth = OAuth(app)
    oauth.register(
        name="huggingface",
        client_id=os.environ.get("OAUTH_CLIENT_ID"),
        client_secret=os.environ.get("OAUTH_CLIENT_SECRET"),
        server_metadata_url=(
            f"{os.environ.get('OPENID_PROVIDER_URL', 'https://huggingface.co')}"
            "/.well-known/openid-configuration"
        ),
        client_kwargs={
            "scope": os.environ.get("OAUTH_SCOPES", "openid profile"),
        },
    )
    _oauth = oauth
    return oauth


def get_oauth() -> OAuth:
    if _oauth is None:
        raise RuntimeError("OAuth not initialized; call init_oauth(app) first")
    return _oauth


def is_dev_mode() -> bool:
    """True when the synthetic-user auth bypass is active.

    Gated by ``INSPECTOR_DEV_MODE=1`` (set automatically by ``app.py`` when
    running locally outside pytest; explicit ``0`` forces it off). HF Space
    deploys never see it on.
    """
    return os.environ.get("INSPECTOR_DEV_MODE") == "1"


def is_oauth_configured() -> bool:
    """True when both the HF client id and the session secret are available."""
    if not os.environ.get("OAUTH_CLIENT_ID"):
        return False
    try:
        get_session_secret()
    except MissingSecret:
        return False
    return True


# ---- Signed cookie helpers ----


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_session_secret(), salt=SESSION_SALT)


def encode_session(*, login: str, hf_user_id: str, iat: int | None = None) -> str:
    """Sign and return the identity-cookie payload."""
    payload = {
        "login": login,
        "hf_user_id": hf_user_id,
        "iat": iat if iat is not None else int(time.time()),
    }
    return _serializer().dumps(payload)


def decode_session(cookie_val: str) -> dict | None:
    """Return the decoded payload or ``None`` if missing/invalid/expired."""
    if not cookie_val:
        return None
    try:
        return _serializer().loads(cookie_val, max_age=SESSION_COOKIE_MAX_AGE)
    except SignatureExpired:
        logger.info("session cookie expired")
        return None
    except BadSignature:
        logger.warning("session cookie signature invalid")
        return None
    except MissingSecret:
        # Session secret unset on this deploy — treat as anonymous.
        return None


# ---- Current-user surface ----


@dataclass(frozen=True)
class User:
    hf_user_id: str
    login: str
    role: Role  # always live; resolved per request via access.resolve_role


def current_user() -> User | None:
    """Read the identity cookie and return the live ``User`` or ``None``.

    ``role`` is resolved fresh on every call via ``access.resolve_role`` —
    the cookie does not carry it, so role revocation takes effect on the
    very next request without forcing re-login.

    In dev mode (``INSPECTOR_DEV_MODE=1``) this short-circuits OAuth and
    returns the synthetic dev user driven by ``inspector_dev_role``.
    """
    if is_dev_mode():
        return _dev_current_user()
    cookie_val = request.cookies.get(SESSION_COOKIE_NAME, "")
    payload = decode_session(cookie_val)
    if payload is None:
        return None
    hf_user_id = payload.get("hf_user_id")
    login = payload.get("login")
    if not hf_user_id or not login:
        return None
    role = access.resolve_role(hf_user_id)
    return User(hf_user_id=hf_user_id, login=login, role=role)


def _dev_current_user() -> User | None:
    """Dev-mode synthetic user. ``"anonymous"`` cookie value → None.

    Each role gets its own ``hf_user_id`` (``dev-<role>``) so flipping the
    role switcher in dev simulates switching between distinct admin users
    in prod — per-user dismissals and claim ownership scope correctly
    instead of collapsing onto a single shared ``dev-local`` user.
    """
    raw = request.cookies.get(DEV_ROLE_COOKIE_NAME, "owner") or "owner"
    if raw == "anonymous":
        return None
    try:
        role = Role(raw)
    except ValueError:
        # Garbage cookie — don't 500 a dev page, fall back to owner.
        role = Role.OWNER
    return User(
        hf_user_id=f"dev-{role.value}",
        login=f"dev-{role.value}",
        role=role,
    )
