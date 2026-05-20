"""Quran.Foundation endpoint + credential config (env-driven).

Values verified live this session:
- Pre-prod OAuth issuer: https://prelive-oauth2.quran.foundation
- Pre-prod user-API base: https://apis-prelive.quran.foundation/auth/v1
- Token auth method: client_secret_basic (HTTP Basic) — REQUIRED; the client
  rejects client_secret_post.
- User-API scope: "openid offline_access user collection".

Creds live in ``inspector/.env`` (gitignored), loaded by ``app.py``.
"""

from __future__ import annotations

import os
from typing import Final

# --- Pre-prod (User APIs / OAuth) ---
PREPROD_ISSUER: Final[str] = "https://prelive-oauth2.quran.foundation"
PREPROD_AUTHORIZE_URL: Final[str] = f"{PREPROD_ISSUER}/oauth2/auth"
PREPROD_TOKEN_URL: Final[str] = f"{PREPROD_ISSUER}/oauth2/token"
PREPROD_USER_API_BASE: Final[str] = "https://apis-prelive.quran.foundation/auth/v1"

# Scope required for user APIs (bookmarks live under the `user` scope).
USER_API_SCOPE: Final[str] = "openid offline_access user collection"

# Token TTL safety margin (seconds) — refresh slightly early.
TOKEN_REFRESH_SKEW: Final[int] = 60

# --- Production (Content APIs / client_credentials) ---
# The content client is a separate, server-to-server credential (no user
# login). Endpoints are PRODUCTION, not pre-prod.
CONTENT_ISSUER: Final[str] = "https://oauth2.quran.foundation"
CONTENT_TOKEN_URL: Final[str] = f"{CONTENT_ISSUER}/oauth2/token"
CONTENT_API_BASE: Final[str] = "https://apis.quran.foundation/content/api/v4"
CONTENT_SCOPE: Final[str] = "content"

# The content OAuth host sits behind Cloudflare, which 403s (error 1010) the
# default urllib/requests User-Agent. A browser-like UA is REQUIRED on both
# token and API requests (verified live this session).
USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def preprod_client_id() -> str:
    return os.environ.get("QF_PREPROD_CLIENT_ID", "").strip()


def preprod_client_secret() -> str:
    return os.environ.get("QF_PREPROD_CLIENT_SECRET", "").strip()


def redirect_uri() -> str:
    """Registered OAuth2 callback. Must match a redirect URI registered on
    the pre-prod client exactly. Override via ``QF_OAUTH_REDIRECT_URI``."""
    return os.environ.get(
        "QF_OAUTH_REDIRECT_URI", "http://localhost:5001/api/qf/callback"
    ).strip()


def is_configured() -> bool:
    """True when pre-prod client credentials are present."""
    return bool(preprod_client_id() and preprod_client_secret())


def content_client_id() -> str:
    return os.environ.get("QF_CONTENT_CLIENT_ID", "").strip()


def content_client_secret() -> str:
    return os.environ.get("QF_CONTENT_CLIENT_SECRET", "").strip()


def content_is_configured() -> bool:
    """True when the Content-API (client_credentials) credentials are present."""
    return bool(content_client_id() and content_client_secret())
