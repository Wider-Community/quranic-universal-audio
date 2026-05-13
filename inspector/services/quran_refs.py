"""Quran reference-data payload served as one immutable static asset.

Bundles the two pieces of fixed reference data the Segments tab needs at
edit time: the Digital Khatt word map (``dk_words``) and the per-verse word
counts (``verse_word_counts``). Both are constant across users, reciters,
chapters, and sessions, so the frontend fetches the payload once per
browser via ``/api/static/quran-refs.json`` (immutable, content-hashed) and
shares it across every tab.

The payload is built lazily on first request and memoised at module scope;
the SHA-256 hash of the serialised bytes powers ETag + cache-busting query
param. The hash changes only when the underlying Digital Khatt script or
surah metadata is rebuilt.
"""
from __future__ import annotations

import hashlib
import threading
from typing import Optional

import orjson

from services.data_loader import get_dk_words_flat, get_word_counts

_lock = threading.Lock()
_payload: Optional[bytes] = None
_hash: Optional[str] = None


def _build() -> tuple[bytes, str]:
    """Serialise the dk_words + verse_word_counts bundle and hash it."""
    verse_word_counts = {
        f"{surah}:{ayah}": n for (surah, ayah), n in get_word_counts().items()
    }
    body = orjson.dumps({
        "dk_words": get_dk_words_flat(),
        "verse_word_counts": verse_word_counts,
    })
    digest = hashlib.sha256(body).hexdigest()[:12]
    return body, digest


def _ensure() -> tuple[bytes, str]:
    global _payload, _hash
    if _payload is not None and _hash is not None:
        return _payload, _hash
    with _lock:
        if _payload is None or _hash is None:
            _payload, _hash = _build()
    return _payload, _hash


def build_payload() -> bytes:
    """Return the serialised Quran-refs JSON body."""
    body, _ = _ensure()
    return body


def payload_hash() -> str:
    """Return the 12-char SHA-256 prefix used as ETag + cache buster."""
    _, digest = _ensure()
    return digest


def reset_cache() -> None:
    """Drop the memoised payload. Test-only — prod has no rebuild trigger."""
    global _payload, _hash
    with _lock:
        _payload = None
        _hash = None
