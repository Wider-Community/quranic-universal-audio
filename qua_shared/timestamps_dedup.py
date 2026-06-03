"""Raw (unfiltered) timestamps v2 + the canonical dedup projection.

The MFA pipeline historically produced an already-deduped, verse-keyed
``timestamps_full.json`` (one merged entry per verse — re-recitations and
cross-verse bleed collapsed at write time). v2 stops discarding that
information at the raw level:

- ``build_raw_v2`` records EVERY accepted segment as its own *occurrence*
  under its output key (compound key for cross-verse; ``"_transitions"``
  for non-verse tokens), with the segment's words verbatim — no
  repeat-pass skip, no word merge.
- ``canonical_occurrence`` projects a v2 document back to the historical
  deduped verse map, so consumers that want the canonical single take
  (the Timestamps tab, the dataset) get byte-identical output to today.

Both faces reuse the pipeline's shared core: ``build_raw_v2`` and
``build_outputs`` feed ``_normalize_from_results``; ``canonical_occurrence``
and ``build_outputs`` feed ``_dedup_core``. There is exactly one
implementation of conversion and of dedup, so the projection can never
drift from what the pipeline wrote. See
``docs/planning/inspector-deploy/v2/phases/13-timestamps-job.md``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

# Conversion + dedup live in the pipeline today (alongside the helpers);
# this module imports them so there is a single implementation. One-
# directional: the pipeline does not import this module.
from qua_shared.timestamps_pipeline import (
    _normalize_from_results,
    _dedup_core,
    _matched_ref_to_output_key,
)

V2_SCHEMA_VERSION = 2

# Bucket for accepted non-verse (transition) segments — kept so the
# canonical projection can reproduce the pipeline exactly, but excluded
# from per-chapter shards (split_to_shards skips ``_``-prefixed keys).
_TRANSITION_KEY = "_transitions"


def build_raw_v2(
    chapters: list[dict],
    results_by_ch: dict[int, list[tuple[int, dict]]],
    audio_category: str,
) -> dict[str, Any]:
    """Build the unfiltered v2 timestamps document from MFA results.

    Returns ``{"_meta": {"mfa_failures": [...], "schema_version": 2},
    "<output_key>": [occurrence, ...]}`` where ``output_key`` is the
    single-verse key (``"1:1"``), the compound cross-verse key
    (``"1:1:3-1:2:2"``), or ``"_transitions"``. Each occurrence is the
    normalized shape from ``_normalize_from_results``::

        {"ch_ref", "seg_index", "matched_ref", "time_start", "time_end",
         "words_by_verse": {verse_key: [[widx, s, e, letters, phones]...]},
         "segment_uid"}

    NO repeat-pass skip and NO word merge — every accepted segment is a
    distinct occurrence. Failed segments are recorded only in
    ``_meta.mfa_failures`` (with ``seg`` + ref for run reconstruction).
    """
    norm, failures = _normalize_from_results(chapters, results_by_ch, audio_category)
    raw: dict[str, Any] = {}
    for occs in norm.values():
        for occ in occs:
            key = _matched_ref_to_output_key(occ["matched_ref"]) or _TRANSITION_KEY
            raw.setdefault(key, []).append(occ)
    for key in raw:
        raw[key].sort(key=lambda o: (o["ch_ref"], o["seg_index"]))
    raw["_meta"] = {"mfa_failures": failures, "schema_version": V2_SCHEMA_VERSION}
    return raw


def canonical_occurrence(
    v2_doc: dict[str, Any],
    audio_category: str,
    seed_existing: dict | None = None,
) -> dict[str, Any]:
    """Project a v2 raw document to the historical deduped verse map.

    Regroups occurrences (+ failures) by chapter via the occurrence's
    ``ch_ref``, reconstructs the positional ``matched_refs`` list each
    chapter needs for repeat-pass run detection, and runs the SAME
    ``_dedup_core`` the live pipeline uses. Returns ``full_data`` — the
    verse-keyed deduped map (byte-identical to the historical
    ``timestamps_full.json`` body).
    """
    occ_by_ch: dict[str, list] = defaultdict(list)
    refs_by_ch: dict[str, dict[int, str]] = defaultdict(dict)

    for key, occs in v2_doc.items():
        if key == "_meta":
            continue
        for occ in occs:
            ch = occ["ch_ref"]
            occ_by_ch[ch].append(occ)
            refs_by_ch[ch][occ["seg_index"]] = occ["matched_ref"]

    meta = v2_doc.get("_meta", {}) or {}
    for fail in (meta.get("mfa_failures") or []):
        ch = str(fail.get("verse", ""))
        seg = fail.get("seg")
        if seg is not None and ch in occ_by_ch:
            # Only fill run-reconstruction refs for chapters that produced
            # at least one occurrence (others contribute nothing to full_data).
            refs_by_ch[ch].setdefault(seg, fail.get("ref", ""))

    chapters_norm = []
    for ch, occs in occ_by_ch.items():
        seg_map = refs_by_ch[ch]
        max_idx = max(seg_map) if seg_map else -1
        matched_refs = [seg_map.get(i, "") for i in range(max_idx + 1)]
        chapters_norm.append({
            "ch_ref": ch,
            "matched_refs": matched_refs,
            "occurrences": sorted(occs, key=lambda o: o["seg_index"]),
        })

    full_data, _words = _dedup_core(
        chapters_norm, seed_existing,
        completed_surahs=set(), completed_refs=set(),
        refresh_surahs=None, audio_category=audio_category,
    )
    return full_data


def is_v2(doc: dict) -> bool:
    """True if ``doc`` is a v2 (occurrence-list) document, else v1 (verse-map).

    v2 verse values are lists of occurrences; v1 values are dicts
    (``{"words": [...], ...}``). Detected from the first non-meta entry.
    """
    for key, val in doc.items():
        if key == "_meta":
            continue
        return isinstance(val, list)
    return False


def project_chapter_shard(doc: dict, *, full: bool = False) -> dict:
    """Return the per-chapter shard document to serve to the Timestamps tab.

    - v1 doc → returned unchanged (back-compat for existing shards).
    - v2 doc, ``full=False`` → deduped to the historical verse-map shape via
      ``canonical_occurrence`` (the Timestamps tab sees today's single take).
    - v2 doc, ``full=True`` → returned unchanged (every occurrence; for the
      owner preview / aligner "show all" surface).

    ``_meta`` is preserved either way. ``audio_category`` is read from
    ``_meta`` (``"by_surah"`` / ``"by_ayah"`` or the ``_audio`` variants).
    """
    if not is_v2(doc) or full:
        return doc
    cat = (doc.get("_meta") or {}).get("audio_category") or "by_surah"
    deduped = canonical_occurrence(doc, cat)
    return {"_meta": doc.get("_meta", {}), **deduped}
