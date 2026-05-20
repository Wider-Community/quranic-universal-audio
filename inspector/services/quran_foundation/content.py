"""Quran.Foundation Content API (client_credentials, server-to-server).

Flask-free. Fetches full-surah recitation audio URLs from
``/chapter_recitations/{id}`` so the dashboard player can stream a reciter's
audio through the QF API instead of our own stored CDN link.

Auth is a ``client_credentials`` grant (``content`` scope, HTTP Basic) against
the PRODUCTION issuer — distinct from the pre-prod user-API client in
``oauth.py``. A browser-like User-Agent is required (Cloudflare 1010 blocks
the default UA). The token is cached process-wide; per-reciter chapter-URL maps
are cached by QF reciter id. See ``services/storage/cache.py``.
"""

from __future__ import annotations

import time
from typing import Final

import requests

from services.storage import cache

from . import config

_TIMEOUT_SECONDS: Final[float] = 10.0
# Fallback token lifetime when the issuer omits ``expires_in`` (seconds).
_DEFAULT_TOKEN_TTL: Final[int] = 3600


class QfContentError(RuntimeError):
    """Raised on transport / protocol failure talking to the Content API."""


def _ua_headers(extra: dict | None = None) -> dict:
    headers = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
    if extra:
        headers.update(extra)
    return headers


def get_content_token() -> str:
    """Return a valid content access token, minting + caching as needed."""
    cached = cache.get_qf_content_token()
    now = time.time()
    if cached and cached.get("expires_at", 0) - config.TOKEN_REFRESH_SKEW > now:
        return cached["access_token"]

    cid, secret = config.content_client_id(), config.content_client_secret()
    if not cid or not secret:
        raise QfContentError("QF content client credentials are not configured")
    try:
        resp = requests.post(
            config.CONTENT_TOKEN_URL,
            data={"grant_type": "client_credentials", "scope": config.CONTENT_SCOPE},
            auth=(cid, secret),  # client_secret_basic
            headers=_ua_headers(),
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise QfContentError(f"QF content token request failed: {e}") from e
    if not resp.ok:
        raise QfContentError(
            f"QF content token {resp.status_code}: {resp.text[:200]}"
        )
    body = resp.json()
    access = body.get("access_token")
    if not access:
        raise QfContentError("QF content token response missing access_token")
    expires_in = body.get("expires_in")
    ttl = expires_in if isinstance(expires_in, (int, float)) else _DEFAULT_TOKEN_TTL
    cache.set_qf_content_token({"access_token": access, "expires_at": now + ttl})
    return access


def chapter_audio_urls(qf_reciter_id: int) -> dict[str, str]:
    """Return ``{chapter_number_str: audio_url}`` for a QF chapter reciter.

    One ``GET /chapter_recitations/{id}`` call returns all chapters; the
    result is cached per reciter id (content is immutable).
    """
    key = str(qf_reciter_id)
    cached = cache.get_qf_chapter_urls(key)
    if cached is not None:
        return cached

    token = get_content_token()
    url = f"{config.CONTENT_API_BASE}/chapter_recitations/{qf_reciter_id}"
    try:
        resp = requests.get(
            url,
            headers=_ua_headers(
                {"x-auth-token": token, "x-client-id": config.content_client_id()}
            ),
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise QfContentError(f"QF chapter_recitations failed: {e}") from e
    if not resp.ok:
        raise QfContentError(
            f"QF chapter_recitations {resp.status_code}: {resp.text[:200]}"
        )
    body = resp.json()
    files = body.get("audio_files") if isinstance(body, dict) else None
    if not isinstance(files, list):
        raise QfContentError("QF chapter_recitations response missing audio_files")
    out: dict[str, str] = {}
    for f in files:
        if not isinstance(f, dict):
            continue
        chap = f.get("chapter_id")
        audio_url = f.get("audio_url")
        if chap is not None and isinstance(audio_url, str) and audio_url:
            out[str(chap)] = audio_url
    cache.set_qf_chapter_urls(key, out)
    return out
