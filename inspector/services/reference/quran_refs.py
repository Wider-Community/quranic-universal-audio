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

import orjson

from services.storage.data_loader import get_dk_words_flat, get_word_counts

_lock = threading.Lock()
_payload: bytes | None = None
_hash: str | None = None


def _build() -> tuple[bytes, str]:
    """Serialise the dk_words + verse_word_counts bundle and hash it."""
    verse_word_counts = {f"{surah}:{ayah}": n for (surah, ayah), n in get_word_counts().items()}
    body = orjson.dumps(
        {
            "dk_words": get_dk_words_flat(),
            "verse_word_counts": verse_word_counts,
        }
    )
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


# ---------------------------------------------------------------------------
# matched_ref -> dk_words text resolver
#
# Mirror of `frontend/src/tabs/segments/utils/data/references.ts::dkTextForRef`.
# Server-side derivation of the Arabic text for a canonical
# ``surah:ayah:word-surah:ayah:word`` ref. Migration #5 removed any
# per-seg / per-snapshot text field; this is the canonical source.
# ---------------------------------------------------------------------------

_MAX_AYAH_BOUNDARY = 300  # mirrors references.ts; runaway-ayah guard


def dk_text_for_ref(matched_ref: str | None) -> str:
    """Walk dk_words from the start endpoint through the end endpoint
    (inclusive). Returns ``""`` for malformed or missing input so callers
    can short-circuit on falsy.
    """
    if not matched_ref or "-" not in matched_ref:
        return ""
    start, _, end = matched_ref.partition("-")
    s_parts = start.split(":")
    e_parts = end.split(":")
    if len(s_parts) != 3 or len(e_parts) != 3:
        return ""
    try:
        s_su, s_ay, s_w = int(s_parts[0]), int(s_parts[1]), int(s_parts[2])
        e_su, e_ay, e_w = int(e_parts[0]), int(e_parts[1]), int(e_parts[2])
    except ValueError:
        return ""

    # Segments don't cross surahs in practice; mirror the FE assumption.
    su = s_su
    dk = get_dk_words_flat()
    wc = get_word_counts()

    words: list[str] = []
    ay, w = s_ay, s_w
    while (su, ay, w) <= (e_su, e_ay, e_w):
        t = dk.get(f"{su}:{ay}:{w}")
        if t:
            words.append(t)
        w += 1
        max_w = wc.get((su, ay), 0)
        if w > max_w:
            w = 1
            ay += 1
            if ay > _MAX_AYAH_BOUNDARY:
                break
    return " ".join(words)
