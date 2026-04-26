"""Unified per-segment classifier.

The single source of truth for "which validation categories does this segment
trigger?" — consumed by:

- ``services.validation.detail._build_detail_lists`` (response building).
- ``services.validation.chapter_validation_counts`` (count rollups).
- ``services.validation.snapshot_classifier`` (history snapshots).
- ``validators.validate_segments`` (the CLI report).

Public surface
--------------

``is_ignored_for(seg, category)``
    Honors ``ignored_categories`` (incl. the legacy ``"_all"`` marker and the
    pre-categories ``ignored=True`` boolean).

``classify_flags(seg, ...) -> dict[str, bool|str|None]``
    Internal flag dict; matches the historical detail-builder contract.

``classify_segment(seg, ...) -> list[str]``
    Category list in registry-declared accordion order. ``detail=True`` adds
    ``"low_confidence_detail"`` (the ``< 1.0`` tier) for callers that want
    the detail-tier flag surfaced as a category.

``classify_segment_full(seg, ...) -> dict``
    Full result dict with ``categories``, ``qalqala_letter``,
    ``low_confidence_detail``, and ``end_of_verse``. Used by callers that
    want the auxiliary fields alongside the category list.

``classify_entry(entry, ..., canonical=None) -> dict``
    Walks every segment in an entry, returning
    ``{segment_uid: {"categories": [...], "qalqala_letter": str|None}}``.
    Segments without a ``segment_uid`` get a synthesized index-based key
    (``f"_idx:{i}"``) so the result is always a complete map.

Tie-breakers (B-1 / B-2 / B-3)
------------------------------

- ``repetitions``: ``wrap_word_ranges`` only — ``has_repeated_words`` alone
  does not classify.
- ``boundary_adj``: structural rule first; phoneme-tail mismatch is an
  optional second signal when ``canonical`` is provided.
- ``audio_bleeding``: ``seg_belongs_to_entry`` against the parsed entry-ref
  structure. Audio-URL comparisons are not part of the rule.
"""
from __future__ import annotations

from typing import Any

from config import BOUNDARY_TAIL_K, LOW_CONFIDENCE_DETAIL_THRESHOLD, LOW_CONFIDENCE_THRESHOLD
from constants import MUQATTAAT_VERSES, QALQALA_LETTERS, STANDALONE_REFS, STANDALONE_WORDS
from services.phoneme_matching import tail_phoneme_mismatch
from utils.arabic_text import last_arabic_letter, strip_quran_deco
from utils.references import seg_belongs_to_entry

from services.validation.registry import PER_SEGMENT_CATEGORIES


# ---------------------------------------------------------------------------
# Ignore filter
# ---------------------------------------------------------------------------


def is_ignored_for(seg: dict, category: str) -> bool:
    """Return True when a segment opts out of being classified as ``category``.

    Reads ``seg["ignored_categories"]`` first; the legacy ``"_all"`` marker
    means "ignore every per-segment category". Falls back to the pre-categories
    ``seg["ignored"]`` boolean for fixtures that predate the array shape.
    """
    ic = seg.get("ignored_categories")
    if ic:
        return "_all" in ic or category in ic
    return bool(seg.get("ignored"))


# ---------------------------------------------------------------------------
# Boundary-adjustment rule
# ---------------------------------------------------------------------------


def _check_boundary_adj(
    seg: dict,
    surah: int,
    s_ayah: int,
    s_word: int,
    e_word: int,
    single_word_verses: set,
    canonical: dict | None,
) -> bool:
    """Apply the boundary-adjustment rule to one segment.

    The structural side fires when a one-word segment lands at a position that
    isn't a single-word verse, isn't a muqattaʼat opener, isn't on the
    standalone-ref allow-list, and the matched text isn't a standalone word.

    The phoneme side fires when ``canonical`` phonemes are available and the
    last ``BOUNDARY_TAIL_K`` ASR phonemes diverge from the canonical tail —
    a heuristic for word-boundary drift the structural rule alone misses.
    """
    if is_ignored_for(seg, "boundary_adj"):
        return False
    if (surah, s_ayah) in MUQATTAAT_VERSES:
        return False
    if (surah, s_ayah) in single_word_verses:
        return False

    is_boundary = False
    if s_word == e_word:
        if (surah, s_ayah, s_word) not in STANDALONE_REFS:
            if strip_quran_deco(seg.get("matched_text", "")) not in STANDALONE_WORDS:
                is_boundary = True

    if not is_boundary and canonical and seg.get("phonemes_asr"):
        matched_ref = seg.get("matched_ref", "")
        if tail_phoneme_mismatch(seg["phonemes_asr"], matched_ref, canonical, BOUNDARY_TAIL_K):
            is_boundary = True

    return is_boundary


# ---------------------------------------------------------------------------
# matched_ref parsing
# ---------------------------------------------------------------------------


def _parse_matched_ref(matched_ref: str) -> tuple[int, int, int, int, int] | None:
    """Parse ``"surah:s_ayah:s_word-surah:e_ayah:e_word"`` into a 5-tuple.

    Returns ``None`` for malformed refs; callers treat malformed as
    "no segment-level position" — failed segs short-circuit to the
    ``failed`` category before reaching this helper.
    """
    parts = matched_ref.split("-")
    if len(parts) != 2:
        return None
    sp = parts[0].split(":")
    ep = parts[1].split(":")
    if len(sp) != 3 or len(ep) != 3:
        return None
    try:
        return int(sp[0]), int(sp[1]), int(sp[2]), int(ep[1]), int(ep[2])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Flags-style classifier (internal contract for detail / counts builders)
# ---------------------------------------------------------------------------


def classify_flags(
    seg: dict,
    entry_ref: str,
    is_by_ayah: bool,
    surah: int,
    s_ayah: int,
    e_ayah: int,
    s_word: int,
    e_word: int,
    single_word_verses: set,
    canonical: dict | None,
) -> dict[str, Any]:
    """Return per-category boolean flags + auxiliary fields for one segment.

    Keys:
      - ``failed``, ``audio_bleeding``, ``repetitions``, ``low_confidence``,
        ``low_confidence_detail``, ``cross_verse``, ``boundary_adj``,
        ``muqattaat``, ``qalqala``: bool.
      - ``qalqala_letter``: ``str | None`` — populated when ``qalqala`` fires.
      - ``end_of_verse``: bool — reserved (callers pass ``word_counts`` to
        compute this themselves).
    """
    result: dict[str, Any] = {
        "failed": False,
        "audio_bleeding": False,
        "repetitions": False,
        "low_confidence": False,
        "low_confidence_detail": False,
        "cross_verse": False,
        "boundary_adj": False,
        "muqattaat": False,
        "qalqala": False,
        "qalqala_letter": None,
        "end_of_verse": False,
    }

    matched_ref = seg.get("matched_ref", "")
    confidence = seg.get("confidence", 0.0)

    if not matched_ref:
        # Gate on is_ignored_for so that _all / ignored=True suppresses even
        # the failed flag — the _all marker means "suppress every classification
        # including errors", which is the strongest user-set suppression.
        result["failed"] = not is_ignored_for(seg, "failed")
        return result

    if is_by_ayah and ":" in entry_ref and not seg_belongs_to_entry(matched_ref, entry_ref):
        if not is_ignored_for(seg, "audio_bleeding"):
            result["audio_bleeding"] = True

    if seg.get("wrap_word_ranges") and not is_ignored_for(seg, "repetitions"):
        result["repetitions"] = True

    if confidence < LOW_CONFIDENCE_THRESHOLD and not is_ignored_for(seg, "low_confidence"):
        result["low_confidence"] = True
    if confidence < LOW_CONFIDENCE_DETAIL_THRESHOLD and not is_ignored_for(seg, "low_confidence"):
        result["low_confidence_detail"] = True

    if s_ayah != e_ayah:
        if not is_ignored_for(seg, "cross_verse"):
            result["cross_verse"] = True
    else:
        result["boundary_adj"] = _check_boundary_adj(
            seg, surah, s_ayah, s_word, e_word, single_word_verses, canonical
        )

    if s_word == 1 and (surah, s_ayah) in MUQATTAAT_VERSES:
        if not is_ignored_for(seg, "muqattaat"):
            result["muqattaat"] = True

    last_letter = last_arabic_letter(seg.get("matched_text", ""))
    if last_letter and last_letter in QALQALA_LETTERS and not is_ignored_for(seg, "qalqala"):
        result["qalqala"] = True
        result["qalqala_letter"] = last_letter

    return result


# ---------------------------------------------------------------------------
# Public ergonomic wrappers
# ---------------------------------------------------------------------------


def _flags_to_categories(flags: dict[str, Any], *, detail: bool) -> list[str]:
    """Translate a flags dict to a category list in registry-declared order."""
    cats: list[str] = []
    for cat in PER_SEGMENT_CATEGORIES:
        if flags.get(cat):
            cats.append(cat)
    if detail and flags.get("low_confidence_detail") and "low_confidence" not in cats:
        cats.append("low_confidence_detail")
    return cats


def classify_segment(
    seg: dict,
    *,
    entry_ref: str = "",
    is_by_ayah: bool = False,
    surah: int | None = None,
    s_ayah: int | None = None,
    e_ayah: int | None = None,
    s_word: int | None = None,
    e_word: int | None = None,
    single_word_verses: set | None = None,
    canonical: dict | None = None,
    detail: bool = False,
) -> list[str]:
    """Classify one segment and return the category list.

    Numeric position parameters (``surah``, ``s_ayah``, ``e_ayah``,
    ``s_word``, ``e_word``) are derived from ``seg["matched_ref"]`` when
    omitted. ``single_word_verses`` defaults to the empty set.

    Pass ``detail=True`` to surface the 1.00 cutoff under the synthetic
    ``low_confidence_detail`` category — used by the validation API to
    distinguish counts (< 0.80) from detail-list items (< 1.00).
    """
    matched_ref = seg.get("matched_ref", "")
    if not matched_ref:
        return ["failed"] if not is_ignored_for(seg, "failed") else []

    if surah is None or s_ayah is None or e_ayah is None or s_word is None or e_word is None:
        parsed = _parse_matched_ref(matched_ref)
        if parsed is None:
            return []
        d_surah, d_s_ayah, d_s_word, d_e_ayah, d_e_word = parsed
        if surah is None:
            surah = d_surah
        if s_ayah is None:
            s_ayah = d_s_ayah
        if s_word is None:
            s_word = d_s_word
        if e_ayah is None:
            e_ayah = d_e_ayah
        if e_word is None:
            e_word = d_e_word

    flags = classify_flags(
        seg, entry_ref, is_by_ayah,
        surah, s_ayah, e_ayah, s_word, e_word,
        single_word_verses or set(), canonical,
    )
    return _flags_to_categories(flags, detail=detail)


def classify_segment_full(
    seg: dict,
    *,
    entry_ref: str = "",
    is_by_ayah: bool = False,
    surah: int | None = None,
    s_ayah: int | None = None,
    e_ayah: int | None = None,
    s_word: int | None = None,
    e_word: int | None = None,
    single_word_verses: set | None = None,
    canonical: dict | None = None,
    detail: bool = False,
) -> dict:
    """Like :func:`classify_segment` but returns a dict with auxiliary fields.

    Returned keys: ``categories`` (list[str]), ``qalqala_letter`` (str|None),
    ``low_confidence_detail`` (bool), ``end_of_verse`` (bool).
    """
    matched_ref = seg.get("matched_ref", "")
    if not matched_ref:
        cats = ["failed"] if not is_ignored_for(seg, "failed") else []
        return {
            "categories": cats,
            "qalqala_letter": None,
            "low_confidence_detail": False,
            "end_of_verse": False,
        }

    if surah is None or s_ayah is None or e_ayah is None or s_word is None or e_word is None:
        parsed = _parse_matched_ref(matched_ref)
        if parsed is None:
            return {
                "categories": [],
                "qalqala_letter": None,
                "low_confidence_detail": False,
                "end_of_verse": False,
            }
        d_surah, d_s_ayah, d_s_word, d_e_ayah, d_e_word = parsed
        if surah is None:
            surah = d_surah
        if s_ayah is None:
            s_ayah = d_s_ayah
        if s_word is None:
            s_word = d_s_word
        if e_ayah is None:
            e_ayah = d_e_ayah
        if e_word is None:
            e_word = d_e_word

    flags = classify_flags(
        seg, entry_ref, is_by_ayah,
        surah, s_ayah, e_ayah, s_word, e_word,
        single_word_verses or set(), canonical,
    )
    return {
        "categories": _flags_to_categories(flags, detail=detail),
        "qalqala_letter": flags.get("qalqala_letter"),
        "low_confidence_detail": bool(flags.get("low_confidence_detail")),
        "end_of_verse": bool(flags.get("end_of_verse")),
    }


def classify_entry(
    entry: dict,
    *,
    is_by_ayah: bool | None = None,
    single_word_verses: set | None = None,
    canonical: dict | None = None,
    detail: bool = False,
) -> dict[str, dict]:
    """Classify every segment in an entry.

    Returns ``{key: {"categories": [...], "qalqala_letter": str|None}}``,
    keyed by ``segment_uid`` when present and otherwise by ``"_idx:<n>"``.
    ``is_by_ayah`` is inferred from the entry-ref shape (``"S:V"`` form) when
    not supplied.
    """
    entry_ref = entry.get("ref", "")
    if is_by_ayah is None:
        is_by_ayah = ":" in entry_ref

    out: dict[str, dict] = {}
    for i, seg in enumerate(entry.get("segments", [])):
        uid = seg.get("segment_uid") or f"_idx:{i}"
        info = classify_segment_full(
            seg,
            entry_ref=entry_ref,
            is_by_ayah=is_by_ayah,
            single_word_verses=single_word_verses,
            canonical=canonical,
            detail=detail,
        )
        out[uid] = {
            "categories": info["categories"],
            "qalqala_letter": info["qalqala_letter"],
        }
    return out


__all__ = [
    "is_ignored_for",
    "classify_flags",
    "classify_segment",
    "classify_segment_full",
    "classify_entry",
    "_check_boundary_adj",
]
