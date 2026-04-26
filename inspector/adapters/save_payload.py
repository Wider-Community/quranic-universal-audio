"""Adapter: incoming save payload -> canonical segment dicts.

Provides ``make_seg`` — extracted from ``services/save.py:_make_seg`` — as the
single lookup+merge logic for building a canonical segment from a payload
segment dict plus existing on-disk segments.  ``services/save.py`` calls this
adapter internally; the route shape is unchanged (MUST-1).
"""

from __future__ import annotations

from services.validation.registry import filter_persistent_ignores
from utils.references import normalize_ref


def make_seg(
    s: dict,
    existing_by_time: dict,
    existing_by_uid: dict,
    word_counts: dict,
) -> dict:
    """Build a canonical segment dict, preserving fields from an existing match.

    Lookup priority for the existing segment:
    1. Time-key match ``(time_start, time_end)``.
    2. UID match (``segment_uid`` from the payload).

    MUST-7 semantics for ``ignored_categories``:
    - Key present in payload (including ``[]``) → apply ``filter_persistent_ignores``.
    - Key absent → preserve the existing entry-side value.
    - Legacy ``ignored=true`` (no ``ignored_categories``) → emit ``["_all"]``.
    """
    existing = existing_by_time.get((s.get("time_start", 0), s.get("time_end", 0)), {})
    if not existing:
        uid = s.get("segment_uid", "")
        if uid:
            existing = existing_by_uid.get(uid, {})

    phonemes = s.get("phonemes_asr", "") or existing.get("phonemes_asr", "")
    seg_uid = s.get("segment_uid", "") or existing.get("segment_uid", "")

    result: dict = {
        "segment_uid": seg_uid,
        "time_start": s.get("time_start", 0),
        "time_end": s.get("time_end", 0),
        "matched_ref": normalize_ref(s.get("matched_ref", ""), word_counts),
        "matched_text": s.get("matched_text", ""),
        "confidence": s.get("confidence", 0.0),
        "phonemes_asr": phonemes,
    }

    wrap = s.get("wrap_word_ranges") or existing.get("wrap_word_ranges")
    if wrap:
        result["wrap_word_ranges"] = wrap
    if s.get("has_repeated_words") or existing.get("has_repeated_words"):
        result["has_repeated_words"] = True

    if "ignored_categories" in s:
        ic = filter_persistent_ignores(s.get("ignored_categories") or [])
        result["ignored_categories"] = list(ic)
    else:
        ic = filter_persistent_ignores(existing.get("ignored_categories") or [])
        if ic:
            result["ignored_categories"] = ic

    if (
        "ignored_categories" not in result
        and "ignored_categories" not in s
        and (s.get("ignored") or existing.get("ignored"))
    ):
        result["ignored_categories"] = ["_all"]

    return result


def build_seg_lookups(matching: list[dict]) -> tuple[dict, dict]:
    """Build ``(by_time, by_uid)`` lookups over matching entry segments.

    Used by the full-replace and patch save paths to locate existing
    segments for field preservation.
    """
    existing_by_time: dict = {}
    existing_by_uid: dict = {}
    for e in matching:
        for seg in e.get("segments", []):
            key = (seg.get("time_start", 0), seg.get("time_end", 0))
            existing_by_time[key] = seg
            uid = seg.get("segment_uid", "")
            if uid:
                existing_by_uid[uid] = seg
    return existing_by_time, existing_by_uid
