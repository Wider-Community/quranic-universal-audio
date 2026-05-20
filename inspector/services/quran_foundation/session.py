"""Signed ``qf_session`` cookie holding the per-user QF token (server-side).

Mirrors the ``itsdangerous`` pattern in ``services/auth/auth.py``. The token
never reaches the browser — only this signed blob does, and routes read it
server-side to inject ``x-auth-token`` on outbound QF calls.

Payload: ``{access_token, refresh_token, expires_at, login?, dev?}``.

In local dev (``INSPECTOR_DEV_MODE=1``) the session secret may be unset; we
fall back to a fixed dev secret so the dev-stub login works without seeding a
real ``INSPECTOR_SESSION_SECRET``. Production always uses the real secret.
"""

from __future__ import annotations

import logging
import time
from typing import Final

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from services.auth.auth import is_dev_mode
from services.auth.secrets_guard import MissingSecret, get_session_secret

logger = logging.getLogger(__name__)

QF_SESSION_COOKIE_NAME: Final[str] = "qf_session"
QF_OAUTH_TMP_COOKIE_NAME: Final[str] = "qf_oauth_tmp"
QF_SESSION_SALT: Final[str] = "qf-session-v1"
QF_OAUTH_TMP_SALT: Final[str] = "qf-oauth-tmp-v1"
QF_SESSION_MAX_AGE: Final[int] = 60 * 60 * 24 * 7  # 1 week
QF_OAUTH_TMP_MAX_AGE: Final[int] = 600  # 10 min — login → callback window

# Dev fallback so the dev-stub login works without a seeded session secret.
_DEV_SECRET: Final[str] = "dev-insecure-qf-session-secret-padding-0123456789abcd"


def _secret() -> str:
    try:
        return get_session_secret()
    except MissingSecret:
        if is_dev_mode():
            return _DEV_SECRET
        raise


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(), salt=salt)


# ---- qf_session (long-lived token holder) ----


def encode_session(payload: dict) -> str:
    return _serializer(QF_SESSION_SALT).dumps(payload)


def decode_session(cookie_val: str) -> dict | None:
    if not cookie_val:
        return None
    try:
        return _serializer(QF_SESSION_SALT).loads(cookie_val, max_age=QF_SESSION_MAX_AGE)
    except (SignatureExpired, BadSignature):
        return None
    except MissingSecret:
        return None


def session_from_token(token: dict, *, login: str | None = None, dev: bool = False) -> str:
    """Build a signed session cookie value from an OAuth token response."""
    expires_in = int(token.get("expires_in", 3600))
    payload = {
        "access_token": token.get("access_token", ""),
        "refresh_token": token.get("refresh_token", ""),
        "expires_at": int(time.time()) + expires_in,
        "login": login,
        "dev": dev,
    }
    return encode_session(payload)


# ---- qf_oauth_tmp (short-lived PKCE/state between login and callback) ----


def encode_oauth_tmp(payload: dict) -> str:
    return _serializer(QF_OAUTH_TMP_SALT).dumps(payload)


def decode_oauth_tmp(cookie_val: str) -> dict | None:
    if not cookie_val:
        return None
    try:
        return _serializer(QF_OAUTH_TMP_SALT).loads(
            cookie_val, max_age=QF_OAUTH_TMP_MAX_AGE
        )
    except (SignatureExpired, BadSignature, MissingSecret):
        return None
