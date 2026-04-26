"""Adapter: detailed.json entries list <-> segment dicts with backfilled UIDs.

``load_entries`` reads raw JSON entries, calls uid backfill, and returns the
same list structure (list of entry dicts, each with a ``segments`` list) with
``segment_uid`` guaranteed on every segment.

``entries_to_json_doc`` reconstructs the ``{"_meta": ..., "entries": ...}``
document ready for atomic write.
"""

from __future__ import annotations

import json
from pathlib import Path

from domain.identity import backfill_entries_uids


def load_entries(path: Path) -> tuple[dict, list[dict]]:
    """Load *path* (detailed.json), backfill missing UIDs, return ``(meta, entries)``.

    The returned *entries* list is mutated in place with any newly derived
    ``segment_uid`` values.  The caller is responsible for persisting the
    mutated entries to disk (on the next save) so that UIDs are stable across
    reload cycles (MUST-4).
    """
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    meta: dict = doc.get("_meta", {})
    entries: list[dict] = doc.get("entries", [])
    backfill_entries_uids(entries)
    return meta, entries


def entries_to_json_doc(meta: dict, entries: list[dict]) -> dict:
    """Reconstruct the full detailed.json document dict from *meta* + *entries*."""
    return {"_meta": meta, "entries": entries}
