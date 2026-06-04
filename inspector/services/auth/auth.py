"""HF OAuth + signed-cookie session.

OAuth-state store + one cookie surface:
- The short-lived OAuth state/nonce between ``/authorize`` and ``/callback``
  lives in a server-side in-process cache (``_state_cache``), NOT in Flask's
  session cookie. On HF Spaces the app runs inside a cross-site
  ``huggingface.co`` iframe where that cookie is third-party and Safari's ITP
  drops it, so Authlib raised ``MismatchingStateError`` on the callback. A
  server-side store keeps the embedded login working with no cookie
  round-trip. Safe because the app is pinned to a single worker (see
  ``app.py`` ``_assert_single_worker``).
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
import threading
import time
from dataclasses import dataclass

from authlib.integrations.flask_client import FlaskIntegration, OAuth
from flask import request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from qua_shared.schemas import Role

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
# between real HF users in prod: claims, audit actor records, and per-admin
# view marks (request_views / review_views) are scoped per role rather than
# collapsing onto one shared ``dev-local`` user. ``DEV_USER_HF_ID`` is kept
# as the legacy default for any caller that still references it (no in-tree
# callers do).
DEV_ROLE_COOKIE_NAME = "inspector_dev_role"
DEV_USER_HF_ID = "dev-local"
DEV_USER_LOGIN = "dev"
DEV_ROLE_VALUES = ("owner", "maintainer", "contributor", "anonymous")

_oauth: OAuth | None = None

# TTL for the post-login return path we stash alongside Authlib's own state
# entry (Authlib's state uses the integration's own expires_in). 10 min
# comfortably covers a human completing the HF consent screen.
_RETURN_PATH_TTL = 600


class _TTLCache:
    """Tiny in-process TTL cache for the OAuth state + return path.

    Read/written through ``get(key)`` / ``set(key, value, expires)`` /
    ``delete(key)`` by ``_CacheStateIntegration`` and the return-path helpers.
    See the module docstring for why a server-side store is needed on HF
    Spaces. The single-worker invariant (``app.py``) makes a per-process dict
    safe.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def get(self, key: str):
        now = time.time()
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at and expires_at < now:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: str, value, expires: float | None = None) -> None:
        expires_at = time.time() + expires if expires else 0.0
        with self._lock:
            # Opportunistically drop expired entries so abandoned logins don't
            # accumulate unbounded.
            if len(self._store) > 256:
                now = time.time()
                self._store = {k: v for k, v in self._store.items() if not v[0] or v[0] >= now}
            self._store[key] = (expires_at, value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)


_state_cache = _TTLCache()


class _CacheStateIntegration(FlaskIntegration):
    """Keep the OAuth state entirely in ``_state_cache`` — never the session.

    Authlib's stock integration writes an ``exp`` marker to the Flask session
    even when a ``cache`` is configured, and ``get_state_data`` bails out if
    that session entry is missing. Inside the cross-site HF iframe the session
    cookie doesn't round-trip (Safari drops it), so the stock path still raises
    ``MismatchingStateError``. Overriding the three state hooks to use only the
    cache makes the callback succeed with no cookie at all.
    """

    def _state_key(self, state: str) -> str:
        return f"_state_{self.name}_{state}"

    def get_state_data(self, session, state):  # noqa: ARG002 — session unused by design
        if not state:
            return None
        return self.cache.get(self._state_key(state))

    def set_state_data(self, session, state, data):  # noqa: ARG002
        self.cache.set(self._state_key(state), data, self.expires_in)

    def clear_state_data(self, session, state):  # noqa: ARG002
        if state:
            self.cache.delete(self._state_key(state))


class _CacheStateOAuth(OAuth):
    """Flask ``OAuth`` registry that stores OAuth state server-side."""

    framework_integration_cls = _CacheStateIntegration


def remember_return_path(state: str, path: str) -> None:
    """Stash the post-login return path keyed by the OAuth ``state``.

    Lives alongside Authlib's own state entry in the server-side cache so the
    callback can recover the redirect target without a session cookie.
    """
    _state_cache.set(f"return_{state}", path, _RETURN_PATH_TTL)


def pop_return_path(state: str | None) -> str | None:
    """Return (and clear) the stashed post-login return path, or ``None``."""
    if not state:
        return None
    key = f"return_{state}"
    val = _state_cache.get(key)
    _state_cache.delete(key)
    return val if isinstance(val, str) else None


def init_oauth(app) -> OAuth:
    """Register the HF OAuth provider on the Flask app. Idempotent."""
    global _oauth
    if _oauth is not None:
        return _oauth
    # _CacheStateOAuth keeps the OAuth state in _state_cache instead of the
    # Flask session cookie (third-party and dropped by Safari inside the HF
    # iframe). The cache is wired in via the registry's `cache` slot.
    oauth = _CacheStateOAuth(app, cache=_state_cache)
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
    in prod — per-admin view marks and claim ownership scope correctly
    instead of collapsing onto a single shared ``dev-local`` user.

    A per-role pair of env vars (``INSPECTOR_DEV_<ROLE>_HF_ID`` /
    ``INSPECTOR_DEV_<ROLE>_LOGIN``) overrides the synthetic identity —
    useful when local dev hits the prod bucket and audit entries should
    be attributed to a real HF user rather than ``dev-owner``.
    """
    raw = request.cookies.get(DEV_ROLE_COOKIE_NAME, "owner") or "owner"
    if raw == "anonymous":
        return None
    try:
        role = Role(raw)
    except ValueError:
        # Garbage cookie — don't 500 a dev page, fall back to owner.
        role = Role.OWNER
    upper = role.value.upper()
    hf_user_id = os.environ.get(f"INSPECTOR_DEV_{upper}_HF_ID") or f"dev-{role.value}"
    login = os.environ.get(f"INSPECTOR_DEV_{upper}_LOGIN") or f"dev-{role.value}"
    return User(
        hf_user_id=hf_user_id,
        login=login,
        role=role,
    )
