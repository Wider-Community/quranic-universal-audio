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

import re
import threading
import time
from typing import Final

import requests

from services.storage import cache

from . import config

_TIMEOUT_SECONDS: Final[float] = 10.0
# Fallback token lifetime when the issuer omits ``expires_in`` (seconds).
_DEFAULT_TOKEN_TTL: Final[int] = 3600
# After a token-mint failure, fast-fail subsequent mints for this long so an
# upstream outage doesn't make every concurrent request hang on the timeout.
_TOKEN_FAIL_COOLDOWN_SECS: Final[float] = 20.0
# Serialises token minting: concurrent cold-cache requests share one mint
# attempt instead of each hammering the (sometimes slow) token endpoint.
_token_lock = threading.Lock()

# Word-by-word translation languages exposed by the Content API, as
# ``(iso_code, English label)``. ``en`` is first / the default. All 15 entries
# verified live against ``/verses/by_key/...?language=<code>`` this session —
# each returns native-script glosses (the top-level ``language`` param is the
# switch; ``word_translation_language`` silently falls back to English).
CONTENT_WBW_LANGUAGES: Final[list[tuple[str, str]]] = [
    ("en", "English"),
    ("ur", "Urdu"),
    ("id", "Indonesian"),
    ("bn", "Bengali"),
    ("fa", "Persian"),
    ("hi", "Hindi"),
    ("ta", "Tamil"),
    ("tr", "Turkish"),
    ("fr", "French"),
    ("zh", "Chinese"),
    ("ml", "Malayalam"),
    ("sq", "Albanian"),
    ("sd", "Sindhi"),
    ("dv", "Divehi"),
    ("inh", "Ingush"),
]
_WBW_LANG_CODES: Final[frozenset[str]] = frozenset(c for c, _ in CONTENT_WBW_LANGUAGES)

# Languages whose word-by-word set is effectively complete (≤4% of verses leak
# an English fallback word), measured with a full-Quran pass against this API
# (77,429 words / 6,236 verses, English as the reference gloss). The rest carry
# real gaps — Indonesian 19% of verses, Hindi/Turkish ~60%, Tamil 83%, Divehi
# 99% — and are flagged "partial" in the picker so users aren't surprised by
# English mixed into a non-English gloss. See the picker in the Timestamps tab.
COMPLETE_WBW_CODES: Final[frozenset[str]] = frozenset(
    {"en", "ur", "bn", "fa", "fr", "zh", "sq"}
)
_VERSE_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^\d+:\d+$")


class QfContentError(RuntimeError):
    """Raised on transport / protocol failure talking to the Content API."""


def _ua_headers(extra: dict | None = None) -> dict:
    headers = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
    if extra:
        headers.update(extra)
    return headers


def _token_valid(now: float) -> str | None:
    cached = cache.get_qf_content_token()
    if cached and cached.get("expires_at", 0) - config.TOKEN_REFRESH_SKEW > now:
        return cached["access_token"]
    return None


def get_content_token() -> str:
    """Return a valid content access token, minting + caching as needed.

    Minting is single-flighted (``_token_lock``) so concurrent cold-cache
    requests share one attempt, and a short cooldown after a failure makes
    subsequent requests fast-fail instead of each hanging on the timeout while
    the upstream token endpoint is degraded.
    """
    now = time.time()
    token = _token_valid(now)
    if token:
        return token

    cooldown = cache.get_qf_token_cooldown()
    if cooldown and cooldown > now:
        raise QfContentError("QF content token temporarily unavailable (cooldown)")

    with _token_lock:
        # Re-check under the lock: another thread may have minted (or tripped
        # the cooldown) while we were waiting.
        now = time.time()
        token = _token_valid(now)
        if token:
            return token
        cooldown = cache.get_qf_token_cooldown()
        if cooldown and cooldown > now:
            raise QfContentError("QF content token temporarily unavailable (cooldown)")

        cid, secret = config.content_client_id(), config.content_client_secret()
        if not cid or not secret:
            raise QfContentError("QF content client credentials are not configured")
        try:
            resp = requests.post(
                config.CONTENT_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "scope": config.CONTENT_SCOPE,
                },
                auth=(cid, secret),  # client_secret_basic
                headers=_ua_headers(),
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            cache.set_qf_token_cooldown(time.time() + _TOKEN_FAIL_COOLDOWN_SECS)
            raise QfContentError(f"QF content token request failed: {e}") from e
        if not resp.ok:
            cache.set_qf_token_cooldown(time.time() + _TOKEN_FAIL_COOLDOWN_SECS)
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


def word_by_word(verse_key: str, language: str = "en") -> dict[str, str]:
    """Return ``{location: gloss}`` for one ayah's word-by-word translation.

    ``verse_key`` is ``"surah:ayah"`` (e.g. ``"2:255"``); ``location`` keys are
    ``"surah:ayah:word"`` — the same join key the Timestamps tab carries on
    each ``TsWord``. Unknown ``language`` codes fall back to English. The
    ayah-number glyph (``char_type_name == "end"``) is filtered out. Result is
    cached per ``(verse_key, language)`` — content is immutable.
    """
    if not _VERSE_KEY_RE.match(verse_key):
        raise QfContentError(f"invalid verse_key: {verse_key!r}")
    lang = language if language in _WBW_LANG_CODES else "en"

    cache_key = f"{verse_key}|{lang}"
    cached = cache.get_qf_wbw(cache_key)
    if cached is not None:
        return cached

    token = get_content_token()
    url = f"{config.CONTENT_API_BASE}/verses/by_key/{verse_key}"
    try:
        resp = requests.get(
            url,
            params={
                "words": "true",
                "language": lang,
                "word_fields": "location,translation",
            },
            headers=_ua_headers(
                {"x-auth-token": token, "x-client-id": config.content_client_id()}
            ),
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise QfContentError(f"QF verses/by_key failed: {e}") from e
    if not resp.ok:
        raise QfContentError(f"QF verses/by_key {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    verse = body.get("verse") if isinstance(body, dict) else None
    words = verse.get("words") if isinstance(verse, dict) else None
    if not isinstance(words, list):
        raise QfContentError("QF verses/by_key response missing verse.words")

    out: dict[str, str] = {}
    for w in words:
        if not isinstance(w, dict) or w.get("char_type_name") == "end":
            continue
        loc = w.get("location")
        if not isinstance(loc, str) or not loc:
            continue
        tr = w.get("translation")
        text = tr.get("text") if isinstance(tr, dict) else None
        out[loc] = text or ""
    cache.set_qf_wbw(cache_key, out)
    return out
