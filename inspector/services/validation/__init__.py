"""Validation engine: 10-category segment validation, chapter validation counts,
and validation log generation.

No Flask imports -- all functions accept parameters and return plain dicts.

Public API (routes use ``from inspector.services.validation import X``):
- ``is_ignored_for``
- ``chapter_validation_counts``
- ``validate_reciter_segments``
- ``run_validation_log``
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from config import BOUNDARY_TAIL_K, LOW_CONFIDENCE_THRESHOLD, SHOW_BOUNDARY_PHONEMES, SURAH_INFO_PATH
from constants import VALIDATION_CATEGORIES
from services import cache
from services.data_loader import get_word_counts, load_detailed
from services.phoneme_matching import get_phoneme_tails
from services.phonemizer_service import get_canonical_phonemes
from utils.formatting import format_ms
from utils.references import chapter_from_ref, is_by_ayah_source, seg_belongs_to_entry

from services.validation._classify import (
    is_ignored_for,
    _classify_segment,
    _check_boundary_adj,
)
from services.validation._missing import _build_missing_words
from services.validation._structural import _check_structural_errors
from services.validation._detail import _build_detail_lists
from services.validation.registry import (
    IssueDefinition,
    IssueRegistry,
    ALL_CATEGORIES,
    PER_SEGMENT_CATEGORIES,
    PER_VERSE_CATEGORIES,
    PER_CHAPTER_CATEGORIES,
    CAN_IGNORE_CATEGORIES,
    AUTO_SUPPRESS_CATEGORIES,
    PERSISTS_IGNORE_CATEGORIES,
    apply_auto_suppress,
    filter_persistent_ignores,
)

# Friendly alias for callers that prefer the plan's external naming.
ISSUE_REGISTRY = IssueRegistry


def chapter_validation_counts(entries: list, chapter: int, meta: dict,
                              canonical: dict | None = None) -> dict:
    """Count validation issues for a single chapter.  Returns ``{category: count}``."""
    word_counts = get_word_counts()
    single_word_verses = {k for k, v in word_counts.items() if v == 1}
    is_by_ayah = is_by_ayah_source(meta.get("audio_source", ""))

    counts = {cat: 0 for cat in VALIDATION_CATEGORIES}
    verse_segments: dict[tuple, list] = defaultdict(list)

    for entry in entries:
        ch = chapter_from_ref(entry["ref"])
        if ch != chapter:
            continue
        entry_ref = entry.get("ref", "")
        for seg in entry.get("segments", []):
            matched_ref = seg.get("matched_ref", "")
            if not matched_ref:
                counts["failed"] += 1
                continue

            parts = matched_ref.split("-")
            if len(parts) != 2:
                if is_by_ayah and ":" in entry_ref and not seg_belongs_to_entry(matched_ref, entry_ref):
                    counts["audio_bleeding"] += 1
                if seg.get("wrap_word_ranges"):
                    counts["repetitions"] += 1
                if seg.get("confidence", 0.0) < LOW_CONFIDENCE_THRESHOLD:
                    counts["low_confidence"] += 1
                continue
            sp = parts[0].split(":")
            ep = parts[1].split(":")
            if len(sp) != 3 or len(ep) != 3:
                continue
            try:
                surah, s_ayah, s_word = int(sp[0]), int(sp[1]), int(sp[2])
                e_ayah, e_word = int(ep[1]), int(ep[2])
            except (ValueError, IndexError):
                continue

            flags = _classify_segment(
                seg, entry_ref, is_by_ayah,
                surah, s_ayah, e_ayah, s_word, e_word,
                single_word_verses, canonical,
            )

            for cat in ("audio_bleeding", "repetitions", "low_confidence",
                        "cross_verse", "boundary_adj", "muqattaat", "qalqala"):
                if flags[cat]:
                    counts[cat] += 1

            if s_ayah != e_ayah:
                for ayah in range(s_ayah, e_ayah + 1):
                    if ayah == s_ayah:
                        wc = word_counts.get((surah, ayah), s_word)
                        verse_segments[(surah, ayah)].append((s_word, wc))
                    elif ayah == e_ayah:
                        verse_segments[(surah, ayah)].append((1, e_word))
                    else:
                        wc = word_counts.get((surah, ayah), 1)
                        verse_segments[(surah, ayah)].append((1, wc))
            else:
                verse_segments[(surah, s_ayah)].append((s_word, e_word))

    for (surah, ayah), seg_list in verse_segments.items():
        expected = word_counts.get((surah, ayah))
        if not expected:
            continue
        covered = set()
        for wf, wt in seg_list:
            covered.update(range(wf, wt + 1))
        missing = set(range(1, expected + 1)) - covered
        if missing:
            counts["missing_words"] += len(missing)

    return counts


def validate_reciter_segments(reciter: str) -> dict:
    """Validate all chapters for a reciter, returning issues grouped by category.

    Returns a plain dict suitable for ``jsonify()``.
    """
    entries = load_detailed(reciter)
    if not entries:
        return None

    word_counts = get_word_counts()
    canonical = get_canonical_phonemes(reciter)
    single_word_verses = {k for k, v in word_counts.items() if v == 1}

    meta = cache.get_seg_meta(reciter)
    is_by_ayah = is_by_ayah_source(meta.get("audio_source", ""))

    detail = _build_detail_lists(entries, is_by_ayah, word_counts, canonical, single_word_verses)
    missing_words = _build_missing_words(detail["verse_segments"], word_counts)
    errors, missing_verses, stats = _check_structural_errors(reciter, entries)

    return {
        "errors": errors,
        "missing_verses": missing_verses,
        "missing_words": missing_words,
        "failed": detail["failed"],
        "low_confidence": detail["low_confidence"],
        "boundary_adj": detail["boundary_adj"],
        "cross_verse": detail["cross_verse"],
        "audio_bleeding": detail["audio_bleeding"],
        "repetitions": detail["repetitions"],
        "muqattaat": detail["muqattaat"],
        "qalqala": detail["qalqala"],
        "stats": stats,
    }


def run_validation_log(reciter_dir: Path) -> None:
    """Run segment validation and write validation.log without printing to console."""
    import io as _io
    from datetime import datetime as _dt
    from validators.validate_segments import validate_reciter, load_word_counts

    wc = load_word_counts(SURAH_INFO_PATH)
    report_path = reciter_dir / "validation.log"

    buf = _io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        validate_reciter(reciter_dir, wc, verbose=True)
    finally:
        sys.stdout = old_stdout

    content = f"Generated: {_dt.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n" + buf.getvalue()
    report_path.write_text(content, encoding="utf-8")
