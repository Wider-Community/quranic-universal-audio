"""Deterministic segment_uid backfill helpers (IS-8).

``NAMESPACE_INSPECTOR`` is a frozen UUID used as the uuid5 namespace for
all segment identity derivation in this project.  The Python and TypeScript
implementations MUST produce identical UIDs for the same
``(chapter, original_index, start_ms)`` input triple.

Algorithm:
    uid = uuid5(NAMESPACE_INSPECTOR, f"{chapter}:{original_index}:{start_ms}")
"""

from __future__ import annotations

import uuid

# Frozen namespace for all inspector segment UIDs.
# This value is stable — changing it would invalidate all backfilled UIDs.
NAMESPACE_INSPECTOR = uuid.UUID("00000000-0000-0000-0000-000000000001")


def derive_uid(chapter: int, original_index: int, start_ms: int) -> str:
    """Return a deterministic UUID5 string for the given segment coordinates.

    Args:
        chapter: Surah number (1–114).
        original_index: Zero-based position of the segment within its chapter,
            as recorded at load time.
        start_ms: ``time_start`` value in milliseconds.

    Returns:
        A lowercase UUID5 string, e.g. ``"xxxxxxxx-xxxx-5xxx-yxxx-xxxxxxxxxxxx"``.
    """
    key = f"{chapter}:{original_index}:{start_ms}"
    return str(uuid.uuid5(NAMESPACE_INSPECTOR, key))


def backfill_entry_uids(entry: dict, chapter: int) -> None:
    """Mutate *entry* in place: assign ``segment_uid`` to any segment that lacks one.

    Uses ``derive_uid(chapter, index, time_start)`` for each segment in
    ``entry["segments"]`` that has no ``segment_uid`` set.  Segments that
    already carry a uid are left untouched (MUST-4).
    """
    for idx, seg in enumerate(entry.get("segments", [])):
        if seg.get("segment_uid"):
            continue
        seg["segment_uid"] = derive_uid(
            chapter=chapter,
            original_index=idx,
            start_ms=int(seg.get("time_start", 0)),
        )


def backfill_entries_uids(entries: list[dict]) -> None:
    """Backfill uids across all entries in a detailed.json ``entries`` list.

    Chapter is parsed from ``entry["ref"]`` (e.g. ``"112"`` → 112).
    Entries with non-integer refs are silently skipped.
    """
    for entry in entries:
        try:
            chapter = int(str(entry.get("ref", "0")).split(":")[0])
        except (ValueError, AttributeError):
            continue
        backfill_entry_uids(entry, chapter)
