"""Segment classification — per-segment category detection.

Pure predicate: given one segment + context, returns which validation
categories it triggers. No accumulation, no list mutation — callers own
the output shape.

Consumed by both ``chapter_validation_counts`` (counts only) and
``validate_reciter_segments`` (builds detail lists). The two callers have
different verse_segments accumulator shapes (2-tuple vs 3-tuple) so
accumulation is intentionally left to each caller — only the boolean flags
are extracted here.
"""

from __future__ import annotations

from config import BOUNDARY_TAIL_K, LOW_CONFIDENCE_DETAIL_THRESHOLD, LOW_CONFIDENCE_THRESHOLD
from constants import MUQATTAAT_VERSES, QALQALA_LETTERS, STANDALONE_REFS, STANDALONE_WORDS
from services.phoneme_matching import tail_phoneme_mismatch
from utils.arabic_text import last_arabic_letter, strip_quran_deco
from utils.references import seg_belongs_to_entry


def is_ignored_for(seg: dict, category: str) -> bool:
    """Check if a segment is ignored for a specific validation category."""
    ic = seg.get("ignored_categories")
    if ic:
        return "_all" in ic or category in ic
    return bool(seg.get("ignored"))


def _check_boundary_adj(
    seg: dict,
    surah: int,
    s_ayah: int,
    s_word: int,
    e_word: int,
    single_word_verses: set,
    canonical: dict | None,
) -> bool:
    """Return True if this segment triggers the boundary_adj category.

    Checks single-word reference criterion first, then phoneme-tail mismatch
    as a secondary signal.
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


def _classify_segment(
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
) -> dict:
    """Return a dict of category → value flags for a single segment.

    Callers use these flags to decide whether to increment a counter or
    append a detail item. Does NOT mutate any external state.

    Returned keys: failed (bool), audio_bleeding (bool), repetitions (bool),
    low_confidence (bool, < LOW_CONFIDENCE_THRESHOLD — for counts),
    low_confidence_detail (bool, < 1.0 — for detail lists),
    cross_verse (bool), boundary_adj (bool),
    muqattaat (bool), qalqala (bool), qalqala_letter (str|None),
    end_of_verse (bool).
    """
    result: dict = {
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
        result["failed"] = True
        return result

    if is_by_ayah and ":" in entry_ref and not seg_belongs_to_entry(matched_ref, entry_ref):
        result["audio_bleeding"] = True

    if seg.get("wrap_word_ranges"):
        result["repetitions"] = True

    if confidence < LOW_CONFIDENCE_THRESHOLD:
        result["low_confidence"] = True
    if confidence < LOW_CONFIDENCE_DETAIL_THRESHOLD:
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
