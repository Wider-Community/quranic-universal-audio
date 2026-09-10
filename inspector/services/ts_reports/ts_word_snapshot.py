"""Report-target fingerprints inside a word-profile (non-Hafs) shard.

A word profile carries no cells, sounds, columns, bridges or animation tokens,
so most of the native fingerprint has nothing to point at. Three identities do
survive the Hafs->target projection, and they are exactly the three the
Timestamps tab still offers on such a delivery:

``verse``     the reading's parts for that ayah — what the ``audio`` and
              ``other`` comment composers target.
``word``      one row: its target ref and the edition's own text.
``boundary``  a gap between two words — its state and the ayah it ends, if any.

``tajweed`` and ``phonemes`` are refused here as they are hidden in the FE
(``nativeOnly`` in ``domain/report-categories.ts``): there is no per-letter fact
to flag, and inventing one would let a reader file a report against nothing.

Boundary geometry mirrors ``boundariesOf`` in the FE's ``compact-shards.ts``:
ids run ``0..len(words)``, id 0 being the lead-in and id ``i`` the gap before
word ``i``. Pause geometry is phoneme-free, so both profiles derive it the same
way and a reader's boundary id means the same thing in either.
"""

from __future__ import annotations

from typing import Any

WORD_SHARD_SCHEMA_VERSION = 14

#: Target kinds a word profile can fingerprint. Everything else is refused.
_KINDS = ("verse", "word", "boundary")


def is_word_document(doc: dict[str, Any]) -> bool:
    """True for a stored word-profile shard of the version this reader knows."""
    meta = doc.get("_meta") or {}
    return meta.get("profile") == "word" and meta.get("schema_version") == WORD_SHARD_SCHEMA_VERSION


def _reading(doc: dict[str, Any], target: dict[str, Any]) -> dict[str, Any] | None:
    reading_id = str(target.get("reading_id", ""))
    return next((row for row in doc.get("readings", []) if row.get("id") == reading_id), None)


def _index(target_id: str) -> int | None:
    try:
        return int(target_id)
    except (TypeError, ValueError):
        return None


def _boundary_spans(reading: dict[str, Any]) -> list[tuple[int, int]]:
    """``(start_ms, end_ms)`` for boundary ids ``0..len(words)``."""
    words = reading.get("words") or []
    if not words:
        return []
    parts = reading.get("parts") or []
    first = parts[0][1] if parts else words[0][2]
    last = parts[-1][2] if parts else words[-1][3]
    spans = [(first, max(first, words[0][2]))]
    for index in range(1, len(words)):
        start = words[index - 1][3]
        spans.append((start, max(start, words[index][2])))
    tail = words[-1][3]
    spans.append((tail, max(tail, last)))
    return spans


def _verse_target(reading: dict[str, Any], verse_key: str, target_id: str):
    if target_id != verse_key:
        return None
    parts = [part for part in reading.get("parts") or [] if part[0] == verse_key]
    if not parts:
        return None
    native = {
        "ref": verse_key,
        "parts": [{"ref": part[0], "t": [part[1], part[2]]} for part in parts],
    }
    return native, (min(part[1] for part in parts), max(part[2] for part in parts))


def _word_target(reading: dict[str, Any], verse_key: str, target_id: str):
    index = _index(target_id)
    words = reading.get("words") or []
    if index is None or not 0 <= index < len(words):
        return None
    ref, text, start_ms, end_ms = words[index]
    if ":".join(ref.split(":")[:2]) != verse_key:
        return None
    # Text is part of the identity, not decoration: a re-stamp that moved the
    # projection would put a different word at this index, and the report must
    # read as stale rather than silently re-point.
    return {"word_id": index, "ref": ref, "text": text}, (start_ms, end_ms)


def _boundary_target(reading: dict[str, Any], verse_key: str, target_id: str):
    index = _index(target_id)
    spans = _boundary_spans(reading)
    words = reading.get("words") or []
    if index is None or not 0 <= index < len(spans):
        return None
    # The gap belongs to the verse of the words on either side of it.
    neighbours = [words[position] for position in (index - 1, index) if 0 <= position < len(words)]
    if verse_key not in {":".join(row[0].split(":")[:2]) for row in neighbours}:
        return None
    boundaries = reading.get("boundaries") or []
    # Boundary id ``i`` follows word ``i - 1``, which is the row whose stored
    # state describes it; the lead-in (id 0) has no preceding word.
    state = boundaries[index - 1] if 0 < index <= len(boundaries) else None
    native = {
        "boundary_id": index,
        "state": None if state is None else state[0],
        "verse_end": None if state is None else state[1],
        "before": None if index == 0 else words[index - 1][0],
        "after": None if index >= len(words) else words[index][0],
    }
    return native, spans[index]


_RESOLVERS = {"verse": _verse_target, "word": _word_target, "boundary": _boundary_target}


def resolve_word_target(
    doc: dict[str, Any], verse_key: str, target: dict[str, Any]
) -> dict[str, Any] | None:
    """The fingerprint for ``target`` in a word-profile shard, or ``None``."""
    if not is_word_document(doc):
        return None
    reading = _reading(doc, target)
    if reading is None:
        return None
    kind = str(target.get("kind", ""))
    resolver = _RESOLVERS.get(kind)
    if resolver is None:
        return None
    resolved = resolver(reading, verse_key, str(target.get("target_id", "")))
    if resolved is None:
        return None
    native, span = resolved
    return {
        # No native analysis exists here, so the field is omitted rather than
        # claiming version 2 — a reader must not expect cells behind it.
        "native_schema_version": None,
        "shard_schema_version": int(doc["_meta"]["schema_version"]),
        "shard_profile": "word",
        "native": native,
        "timing": None if span is None else {"start_ms": span[0], "end_ms": span[1]},
    }


__all__ = ["is_word_document", "resolve_word_target"]
