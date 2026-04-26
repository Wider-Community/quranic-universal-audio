"""Adapter: rebuild segments.json from detailed.json entries (MUST-3).

Extracted verbatim from ``services/save.py:rebuild_segments_json``.  The
on-disk format is verse-aggregated tuples ``[start_word, end_word, t_from, t_to]``
keyed by verse ref string, with a ``_meta`` block preserved from the existing
file.  The tuple shape and ``_meta`` structure are unchanged (MUST-3).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from utils.references import seg_sort_key


def rebuild(reciter_dir: Path, entries: list[dict]) -> None:
    """Regenerate ``segments.json`` in *reciter_dir* from *entries*.

    Reads the existing ``_meta`` block from the current ``segments.json`` (if
    present) and writes a fresh document with the verse-aggregated segment
    tuples sorted by ``seg_sort_key``.
    """
    segments_path = reciter_dir / "segments.json"
    verse_data: dict[str, list] = defaultdict(list)

    for entry in entries:
        for seg in entry.get("segments", []):
            ref = seg.get("matched_ref", "")
            if not ref:
                continue
            parts = ref.split("-")
            if len(parts) != 2:
                continue
            start_parts = parts[0].split(":")
            end_parts = parts[1].split(":")
            if len(start_parts) != 3 or len(end_parts) != 3:
                continue
            try:
                start_sura = int(start_parts[0])
                start_ayah = int(start_parts[1])
                start_word = int(start_parts[2])
                end_ayah = int(end_parts[1])
                end_word = int(end_parts[2])
            except ValueError:
                continue

            t_from = seg.get("time_start", 0)
            t_to = seg.get("time_end", 0)

            if start_ayah == end_ayah:
                verse_data[f"{start_sura}:{start_ayah}"].append(
                    [start_word, end_word, t_from, t_to]
                )
            else:
                verse_data[ref].append(
                    [start_word, end_word, t_from, t_to]
                )

    existing_meta: dict = {}
    if segments_path.exists():
        with open(segments_path, "r", encoding="utf-8") as f:
            try:
                existing_doc = json.load(f)
                existing_meta = existing_doc.get("_meta", {})
            except json.JSONDecodeError:
                pass

    seg_doc: dict = {"_meta": existing_meta}
    for key in sorted(verse_data.keys(), key=seg_sort_key):
        seg_doc[key] = verse_data[key]

    with open(segments_path, "w", encoding="utf-8") as f:
        json.dump(seg_doc, f, ensure_ascii=False)
