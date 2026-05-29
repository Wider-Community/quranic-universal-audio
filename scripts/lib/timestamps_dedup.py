"""Raw (unfiltered) timestamps v2 + the canonical dedup projection.

The MFA pipeline historically produced an already-deduped, verse-keyed
``timestamps_full.json`` (one merged entry per verse — re-recitations and
cross-verse bleed collapsed at write time). v2 stops discarding that
information at the raw level:

- ``build_raw_v2`` records EVERY accepted segment as its own *occurrence*
  under its output key (compound key for cross-verse), with the segment's
  full nested words verbatim — no repeat-pass skip, no word merge.
- ``canonical_occurrence`` (added in the next increment) projects a v2
  document back to the historical deduped verse map, so consumers that
  want the canonical single take (the Timestamps tab, the dataset) get
  byte-identical output to today.

This module is the single home for the dedup rule. ``build_raw_v2`` here
and the to-be-lifted ``build_outputs`` in ``timestamps_pipeline`` feed a
shared core so the deduped projection can never drift from what the
pipeline wrote. See ``docs/planning/inspector-deploy/v2/phases/13-timestamps-job.md``.
"""

from __future__ import annotations

from typing import Any

# Converters live in the pipeline today; they will move here when the
# closure lift lands. Importing them keeps a single implementation in the
# meantime (one-directional: pipeline does not import this module yet).
from scripts.lib.timestamps_pipeline import (
    _convert_result,
    _matched_ref_to_output_key,
)

V2_SCHEMA_VERSION = 2


def build_raw_v2(
    chapters: list[dict],
    results_by_ch: dict[int, list[tuple[int, dict]]],
    audio_category: str,
) -> dict[str, Any]:
    """Build the unfiltered v2 timestamps document from MFA results.

    Args:
        chapters: ``detailed.json`` ``entries`` — each ``{"ref", "segments"[]}``.
        results_by_ch: ``{chapter_index: [(seg_index, mfa_result), ...]}`` —
            exactly the structure the pipeline assembles per beam.
        audio_category: ``"by_surah_audio"`` or ``"by_ayah_audio"``.

    Returns:
        ``{"_meta": {"mfa_failures": [...]}, "<output_key>": [occurrence, ...]}``
        where ``output_key`` is the single-verse key (``"1:1"``) or the
        compound cross-verse key (``"37:151:3-37:152:2"``), and each
        occurrence is::

            {
              "seg_index": int,        # chapter-local order (run reconstruction)
              "matched_ref": str,
              "time_start": int, "time_end": int,   # ms in chapter audio
              "words": [[widx, s_ms, e_ms, [[char,s,e]...], [[phone,s,e]...]]...],
              "segment_uid": str | None,             # nullable passthrough
            }

        NO repeat-pass skip and NO word merge are applied — every accepted
        segment is preserved as a distinct occurrence. Failed segments are
        recorded in ``_meta.mfa_failures`` (carrying ``seg_index`` + ref so
        ``canonical_occurrence`` can reconstruct run contiguity), never as
        occurrences. Transition segments (non-verse ``matched_ref``) are
        dropped, matching the pipeline.
    """
    raw: dict[str, Any] = {}
    failures: list[dict] = []

    for ch_idx, chapter in enumerate(chapters):
        ch_ref = str(chapter.get("ref", ""))
        segments = chapter.get("segments", [])
        for seg_idx, result in results_by_ch.get(ch_idx, []):
            if seg_idx >= len(segments):
                continue
            seg = segments[seg_idx]
            matched_ref = seg.get("matched_ref", "")

            if result.get("status") != "ok":
                failures.append({
                    "verse": ch_ref,
                    "seg": seg_idx,
                    "ref": matched_ref,
                    "error": result.get("error", "unknown"),
                })
                continue

            output_key = _matched_ref_to_output_key(matched_ref)
            if output_key is None:
                # Transition segment (Basmala / Isti'adha / etc.) — no verse
                # home; the pipeline strips these from the verse map too.
                continue

            time_start = int(seg.get("time_start", 0))
            time_end = int(seg.get("time_end", time_start))
            words = _convert_result(result, time_start)

            raw.setdefault(output_key, []).append({
                "seg_index": seg_idx,
                "matched_ref": matched_ref,
                "time_start": time_start,
                "time_end": time_end,
                "words": words,
                "segment_uid": seg.get("segment_uid"),
            })

    # Deterministic occurrence order within each key = chapter seg order.
    for key in raw:
        raw[key].sort(key=lambda o: o["seg_index"])

    raw["_meta"] = {"mfa_failures": failures, "schema_version": V2_SCHEMA_VERSION}
    return raw
