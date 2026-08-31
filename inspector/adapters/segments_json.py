"""Adapter: rebuild segments.json from detailed.json entries (MUST-3).

Extracted verbatim from ``services/save.py:rebuild_segments_json``.  The
on-disk format is verse-aggregated tuples ``[start_word, end_word, t_from, t_to]``
keyed by verse ref string, with a ``_meta`` block preserved from the existing
file.  The tuple shape and ``_meta`` structure are unchanged (MUST-3).

``with_repeated`` opts a caller into the pipeline writer's fifth element,
``{"repeated": [[from_word, to_word], ...]}``, for segments carrying
``wrap_word_ranges``.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from utils.references import seg_sort_key


def _repeated_element(ref_from: str, ref_to: str, wrap_word_ranges: list) -> dict:
    """Build the ``{"repeated": [[from_word, to_word], ...]}`` row element."""
    from utils.repetitions import compute_reading_sequence

    sections = compute_reading_sequence(ref_from, ref_to, wrap_word_ranges)
    return {
        "repeated": [
            [int(sec_from.rsplit(":", 1)[1]), int(sec_to.rsplit(":", 1)[1])]
            for sec_from, sec_to in sections
        ]
    }


def build_segments_doc(
    entries: list[dict],
    existing_meta: dict | None = None,
    *,
    with_repeated: bool = False,
) -> dict:
    """Pure function: build the verse-aggregated segments.json doc from entries.

    Returns ``{"_meta": existing_meta, "<verse_ref>": [[start_word, end_word,
    t_from, t_to], ...], ...}`` sorted by ``seg_sort_key``. The ``_meta`` block
    is preserved from the existing file when supplied; otherwise empty.

    With ``with_repeated`` set, a segment carrying a truthy ``wrap_word_ranges``
    gains a fifth row element describing the reading-order sections.
    """
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

            row = [start_word, end_word, t_from, t_to]
            wrap_ranges = seg.get("wrap_word_ranges")
            if with_repeated and wrap_ranges:
                row.append(_repeated_element(parts[0], parts[1], wrap_ranges))

            if start_ayah == end_ayah:
                verse_data[f"{start_sura}:{start_ayah}"].append(row)
            else:
                verse_data[ref].append(row)

    seg_doc: dict = {"_meta": existing_meta or {}}
    for key in sorted(verse_data.keys(), key=seg_sort_key):
        seg_doc[key] = verse_data[key]
    return seg_doc


def rebuild(reciter_dir: Path, entries: list[dict]) -> None:
    """Regenerate ``segments.json`` in *reciter_dir* from *entries*.

    Local-filesystem convenience wrapper around ``build_segments_doc``;
    consumed by tests and the local-mode save path. The deployed save path
    in ``services/save.py`` uses ``build_segments_doc`` + the storage
    backend instead.
    """
    segments_path = reciter_dir / "segments.json"
    existing_meta: dict = {}
    if segments_path.exists():
        try:
            import orjson

            existing_doc = orjson.loads(segments_path.read_bytes())
            existing_meta = existing_doc.get("_meta", {})
        except Exception:
            pass

    seg_doc = build_segments_doc(entries, existing_meta)

    import orjson

    with open(segments_path, "wb") as f:
        f.write(orjson.dumps(seg_doc))
