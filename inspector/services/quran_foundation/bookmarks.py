"""Bookmarks proxy to QF ``/auth/v1/bookmarks`` + a dev in-memory store.

Flask-free. A QF bookmark is a verse reference (e.g. ``"2:255"``); we
normalize every shape to ``{surah, ayah, key}`` for the frontend.

The exact QF request/response JSON for bookmarks is not yet confirmable live
(the OAuth user flow is blocked on redirect-URI registration), so the real
path normalizes defensively and the wire shape should be re-verified once a
real user token is obtainable. The dev path uses our own in-memory shape so
the FE↔backend wiring is demonstrable today.
"""

from __future__ import annotations

import re
import logging
from typing import Final

import requests

from . import config

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS: Final[float] = 10.0
_KEY_RE: Final[re.Pattern] = re.compile(r"^(\d{1,3}):(\d{1,3})$")

# Dev-only in-memory store (process-local, dev-stub session). Keyed by verse key.
_DEV_STORE: dict[str, dict] = {}


class QfBookmarkError(RuntimeError):
    """Raised on transport / protocol failure talking to QF."""


def normalize_key(surah: int, ayah: int) -> str:
    return f"{int(surah)}:{int(ayah)}"


def _split_key(key: str) -> tuple[int, int] | None:
    m = _KEY_RE.match((key or "").strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _bookmark_dict(key: str) -> dict | None:
    parts = _split_key(key)
    if not parts:
        return None
    surah, ayah = parts
    return {"surah": surah, "ayah": ayah, "key": key}


# ---- Dev path (in-memory) ----


def dev_list() -> list[dict]:
    return list(_DEV_STORE.values())


def dev_add(surah: int, ayah: int) -> dict:
    key = normalize_key(surah, ayah)
    item = {"surah": int(surah), "ayah": int(ayah), "key": key}
    _DEV_STORE[key] = item
    return item


def dev_remove(key: str) -> None:
    _DEV_STORE.pop(key, None)


# ---- Real QF path ----


def _headers(token: str) -> dict:
    return {
        "x-auth-token": token,
        "x-client-id": config.preprod_client_id(),
        "Accept": "application/json",
    }


# Mushaf id used for bookmark create/list (QDC default Hafs mushaf).
_MUSHAF_ID: Final[int] = 1


def _extract_key(raw: dict) -> str | None:
    """Map a QF bookmark record to a ``surah:ayah`` key.

    QF ayah bookmarks look like ``{"type":"ayah","key":<surah>,"verseNumber":<ayah>}``
    where ``key`` is the chapter number. Only ayah bookmarks map to a verse
    key; surah/juz/page bookmarks are skipped (our viewer is verse-level)."""
    t = raw.get("type")
    k = raw.get("key")
    vn = raw.get("verseNumber", raw.get("verse_number"))
    if t == "ayah" and isinstance(k, (int, float)) and vn is not None:
        return f"{int(k)}:{int(vn)}"
    # Tolerant fallbacks for string verse keys.
    for field in ("verse_key", "verseKey"):
        val = raw.get(field)
        if isinstance(val, str) and _KEY_RE.match(val):
            return val
    if isinstance(k, str) and _KEY_RE.match(k):
        return k
    return None


def _rows(body) -> list:
    if isinstance(body, dict):
        return body.get("data") or body.get("bookmarks") or []
    return body if isinstance(body, list) else []


# QF caps the bookmarks page size at 20.
_MAX_FIRST: Final[int] = 20


def _fetch_rows(token: str, first: int = _MAX_FIRST) -> list:
    url = f"{config.PREPROD_USER_API_BASE}/bookmarks"
    try:
        resp = requests.get(
            url,
            headers=_headers(token),
            # NB: the LIST endpoint wants `mushafId` (create body uses `mushaf`);
            # `first` must be <= 20.
            params={"mushafId": _MUSHAF_ID, "first": min(first, _MAX_FIRST)},
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise QfBookmarkError(f"QF bookmarks list failed: {e}") from e
    logger.info("QF list_bookmarks %s body=%s", resp.status_code, resp.text[:500])
    if not resp.ok:
        raise QfBookmarkError(f"QF bookmarks list {resp.status_code}: {resp.text[:200]}")
    return _rows(resp.json())


def list_bookmarks(token: str, *, first: int = _MAX_FIRST) -> list[dict]:
    out: list[dict] = []
    for raw in _fetch_rows(token, first):
        if not isinstance(raw, dict):
            continue
        key = _extract_key(raw)
        item = _bookmark_dict(key) if key else None
        if item:
            out.append(item)
    return out


def add_bookmark(token: str, surah: int, ayah: int) -> dict:
    url = f"{config.PREPROD_USER_API_BASE}/bookmarks"
    # QF ayah bookmark: key = chapter number, verseNumber = ayah (both numeric).
    payload = {
        "mushaf": _MUSHAF_ID,
        "type": "ayah",
        "key": int(surah),
        "verseNumber": int(ayah),
    }
    try:
        resp = requests.post(
            url, headers=_headers(token), json=payload, timeout=_TIMEOUT_SECONDS
        )
    except requests.RequestException as e:
        raise QfBookmarkError(f"QF bookmark add failed: {e}") from e
    logger.info(
        "QF add_bookmark sent=%s -> %s body=%s", payload, resp.status_code, resp.text[:300]
    )
    if not resp.ok:
        raise QfBookmarkError(f"QF bookmark add {resp.status_code}: {resp.text[:200]}")
    return {"surah": int(surah), "ayah": int(ayah), "key": normalize_key(surah, ayah)}


def remove_bookmark(token: str, key: str) -> None:
    # QF deletes by bookmark id (a cuid), not the verse key — look it up first.
    parts = _split_key(key)
    if not parts:
        return
    surah, ayah = parts
    bid = None
    for raw in _fetch_rows(token):
        if not isinstance(raw, dict) or raw.get("type") != "ayah":
            continue
        k = raw.get("key")
        vn = raw.get("verseNumber", raw.get("verse_number"))
        if k is not None and vn is not None and int(k) == surah and int(vn) == ayah:
            bid = raw.get("id")
            break
    if not bid:
        return  # already absent
    url = f"{config.PREPROD_USER_API_BASE}/bookmarks/{bid}"
    try:
        resp = requests.delete(url, headers=_headers(token), timeout=_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        raise QfBookmarkError(f"QF bookmark remove failed: {e}") from e
    if not resp.ok and resp.status_code != 404:
        raise QfBookmarkError(f"QF bookmark remove {resp.status_code}: {resp.text[:200]}")
