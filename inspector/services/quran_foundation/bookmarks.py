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
from typing import Final

import requests

from . import config

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


def _extract_key(raw: dict) -> str | None:
    """Pull a verse key out of a QF bookmark record, tolerating field-name
    variation (key / verse_key / verseKey, or surah+ayah fields)."""
    for field in ("key", "verse_key", "verseKey"):
        val = raw.get(field)
        if isinstance(val, str) and _KEY_RE.match(val):
            return val
    surah = raw.get("surah") or raw.get("chapter") or raw.get("chapter_id")
    ayah = raw.get("ayah") or raw.get("verse") or raw.get("verse_number")
    if surah is not None and ayah is not None:
        return f"{int(surah)}:{int(ayah)}"
    return None


def list_bookmarks(token: str, *, first: int = 50) -> list[dict]:
    url = f"{config.PREPROD_USER_API_BASE}/bookmarks"
    try:
        resp = requests.get(
            url, headers=_headers(token), params={"first": first}, timeout=_TIMEOUT_SECONDS
        )
    except requests.RequestException as e:
        raise QfBookmarkError(f"QF bookmarks list failed: {e}") from e
    if not resp.ok:
        raise QfBookmarkError(f"QF bookmarks list {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    # Tolerate {data: [...]}, {bookmarks: [...]}, or a bare list.
    rows = body.get("data") if isinstance(body, dict) else body
    if rows is None and isinstance(body, dict):
        rows = body.get("bookmarks", [])
    out: list[dict] = []
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        key = _extract_key(raw)
        item = _bookmark_dict(key) if key else None
        if item:
            out.append(item)
    return out


def add_bookmark(token: str, surah: int, ayah: int) -> dict:
    url = f"{config.PREPROD_USER_API_BASE}/bookmarks"
    key = normalize_key(surah, ayah)
    try:
        resp = requests.post(
            url, headers=_headers(token), json={"key": key}, timeout=_TIMEOUT_SECONDS
        )
    except requests.RequestException as e:
        raise QfBookmarkError(f"QF bookmark add failed: {e}") from e
    if not resp.ok:
        raise QfBookmarkError(f"QF bookmark add {resp.status_code}: {resp.text[:200]}")
    return {"surah": int(surah), "ayah": int(ayah), "key": key}


def remove_bookmark(token: str, key: str) -> None:
    url = f"{config.PREPROD_USER_API_BASE}/bookmarks/{key}"
    try:
        resp = requests.delete(url, headers=_headers(token), timeout=_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        raise QfBookmarkError(f"QF bookmark remove failed: {e}") from e
    if not resp.ok and resp.status_code != 404:
        raise QfBookmarkError(f"QF bookmark remove {resp.status_code}: {resp.text[:200]}")
