"""Validation engine: registry-backed segment validation + chapter counts.

No Flask imports -- all functions accept parameters and return plain dicts.

Public API (routes use ``from services.validation import X``):
- ``is_ignored_for``
- ``classify_segment``, ``classify_segment_full``, ``classify_entry``
- ``classify_snapshot``
- ``validate_reciter_segments``
- registry symbols (re-exported)
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from services.storage import cache
from services.storage.data_loader import (
    get_single_word_verses,
    get_word_counts,
    load_detailed,
    load_pipeline_meta,
    load_probe_v2,
    load_seg_verses,
)
from services.activity.history_query import (
    build_resolved_by_edit_index,
    build_split_group_index,
)
from utils.references import is_by_ayah_source

# Phonemizer is no longer loaded in the validate runtime path. The phonemic
# side of boundary_adj is captured at backfill / extraction time via
# ``scripts/backfills/backfill_boundary_adj.py`` (the sole quranic_phonemizer
# consumer in the project) and persisted as ``is_boundary_adj`` on every
# segment. The classifier reads the persisted value instead of recomputing —
# canonical=None throughout the runtime path.

from services.validation.classifier import (
    is_ignored_for,
    is_resolved_by_edit,
    is_suppressed_for,
    classify_flags,
    classify_segment,
    classify_segment_full,
    classify_entry,
    _check_boundary_adj,
)
from services.validation.snapshot_classifier import classify_snapshot
from services.validation.detail import _build_detail_lists
from services.validation._missing import _build_missing_words
from services.validation._structural import _check_structural_errors
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
    filter_persistent_ignores,
)

ISSUE_REGISTRY = IssueRegistry


def _load_resolved_idx_cached(reciter: str) -> dict:
    """Cache-aware wrapper for ``build_resolved_by_edit_index``.

    Hoisted so the parallel fan-out below can submit it as a single callable.
    """
    resolved = cache.get_seg_resolved_by_edit(reciter)
    if resolved is None:
        resolved = build_resolved_by_edit_index(reciter)
        cache.set_seg_resolved_by_edit(reciter, resolved)
    return resolved


def _read_deleted_basmala_chapters(reciter: str) -> set[int]:
    """Read the stripped-basmala set from the ``pipeline_meta.json`` sidecar.

    Hard-fails on missing sidecar (clear deploy signal): silent skip would
    drop basmala_amin counts to 0 without anyone noticing. Run
    ``scripts/backfills/backfill_deleted_basmala.py`` for any reciter that
    pre-dates the extraction-time write.
    """
    meta = load_pipeline_meta(reciter)
    if meta is None:
        raise RuntimeError(
            f"pipeline_meta.json missing for {reciter!r}; "
            "run scripts/backfill_deleted_basmala.py"
        )
    return set(meta.get("deleted_basmala_chapters") or [])


def validate_reciter_segments(reciter: str) -> dict:
    """Validate all chapters for a reciter, returning issues grouped by category.

    Returns a plain dict suitable for ``jsonify()``.
    """
    # Parallel I/O fan-out: four independent bucket reads. SSL recv releases
    # the GIL, so threads cut the wall-clock cost from sum(serial) to
    # max(slowest). Each loader caches its own result via services/cache.py,
    # so the threads don't double-fetch. ``load_seg_verses`` populates the
    # cache that ``_check_structural_errors`` later reads.
    with ThreadPoolExecutor(max_workers=4) as pool:
        f_detailed = pool.submit(load_detailed, reciter)
        f_resolved = pool.submit(_load_resolved_idx_cached, reciter)
        f_probe = pool.submit(load_probe_v2, reciter)
        f_verses = pool.submit(load_seg_verses, reciter)
        entries = f_detailed.result()
        resolved_idx = f_resolved.result()
        probe_failed_uids, probe_meta = f_probe.result()
        f_verses.result()  # prime the seg_verses cache before structural pass

    if not entries:
        return None

    word_counts = get_word_counts()
    # canonical=None: the phonemic side of boundary_adj is captured at backfill
    # time onto each seg's ``is_boundary_adj`` field. Classifier short-circuits
    # on the persisted value; legacy segs without the field fall through to
    # compute_is_boundary_adj with canonical=None → structural side only.
    canonical = None
    single_word_verses = get_single_word_verses()

    meta = cache.get_seg_meta(reciter)
    is_by_ayah = is_by_ayah_source(meta.get("audio_source", ""))

    # Inject resolved-by-edit categories. The transient ``_resolved_by_edit``
    # field is consulted by ``is_resolved_by_edit`` during this validate pass
    # and stripped from every seg before returning so it never reaches disk
    # via the cached entries list. Categories are limited to the soft set in
    # ``RESOLVES_BY_EDIT_CATEGORIES`` (boundary_adj / audio_bleeding /
    # repetitions / low_confidence_v2) -- this is what makes those cards
    # disappear from the accordion once the user has edited from them.
    _injected_segs: list[dict] = []
    if resolved_idx:
        for entry in entries:
            for seg in entry.get("segments", []):
                uid = seg.get("segment_uid")
                if uid and uid in resolved_idx:
                    seg["_resolved_by_edit"] = resolved_idx[uid]
                    _injected_segs.append(seg)

    deleted_basmala_chapters = _read_deleted_basmala_chapters(reciter)
    # Precomputed split-group closures (pure function of cached batch list).
    # Shipped at the response top level as ``split_group_index`` (uid → list of
    # transitive descendants) so the FE can expand accordion cards without
    # walking historyData. Keyed by ROOT uid only — items look up by their
    # own uid client-side.
    split_group_index = build_split_group_index(reciter)

    detail = _build_detail_lists(
        entries, is_by_ayah, word_counts, canonical, single_word_verses,
        probe_failed_uids=probe_failed_uids,
        deleted_basmala_chapters=deleted_basmala_chapters,
    )
    missing_words = _build_missing_words(
        detail["verse_segments"], word_counts, detail["sequence_gaps"]
    )
    errors, missing_verses, stats = _check_structural_errors(reciter, entries)

    # Aggregate counts in registry-declared accordion order. Additive on top
    # of the per-category arrays; the frontend uses it to render badge totals
    # and category-summary widgets without walking every detail array.
    category_counts = {
        "failed": len(detail["failed"]),
        "missing_verses": len(missing_verses),
        "missing_words": len(missing_words),
        "structural_errors": len(errors),
        "low_confidence": len(detail["low_confidence"]),
        "low_confidence_v2": len(detail["low_confidence_v2"]),
        "repetitions": len(detail["repetitions"]),
        "audio_bleeding": len(detail["audio_bleeding"]),
        "boundary_adj": len(detail["boundary_adj"]),
        "cross_verse": len(detail["cross_verse"]),
        "qalqala": len(detail["qalqala"]),
        "muqattaat": len(detail["muqattaat"]),
        "basmala_amin": len(detail["basmala_amin"]),
    }

    result = {
        "errors": errors,
        "structural_errors": errors,  # alias — same list; MUST-1 additive
        "missing_verses": missing_verses,
        "missing_words": missing_words,
        "failed": detail["failed"],
        "low_confidence": detail["low_confidence"],
        "low_confidence_v2": detail["low_confidence_v2"],
        "boundary_adj": detail["boundary_adj"],
        "cross_verse": detail["cross_verse"],
        "audio_bleeding": detail["audio_bleeding"],
        "repetitions": detail["repetitions"],
        "muqattaat": detail["muqattaat"],
        "qalqala": detail["qalqala"],
        "basmala_amin": detail["basmala_amin"],
        "category_counts": category_counts,
        "stats": stats,
        # Precomputed split-group closures keyed by root uid. The FE reads
        # this map instead of walking historyData to expand accordion cards
        # with the full descendant chain after a split.
        "split_group_index": split_group_index,
    }
    if probe_meta is not None:
        result["low_confidence_v2_meta"] = probe_meta

    # Strip the transient injection so the cached entries dict stays clean
    # for the save flow (which serializes ``entries`` directly to disk).
    for seg in _injected_segs:
        seg.pop("_resolved_by_edit", None)

    return result


__all__ = [
    "is_ignored_for",
    "is_resolved_by_edit",
    "is_suppressed_for",
    "classify_flags",
    "classify_segment",
    "classify_segment_full",
    "classify_entry",
    "classify_snapshot",
    "validate_reciter_segments",
    "_build_detail_lists",
    "IssueDefinition",
    "IssueRegistry",
    "ISSUE_REGISTRY",
    "ALL_CATEGORIES",
    "PER_SEGMENT_CATEGORIES",
    "PER_VERSE_CATEGORIES",
    "PER_CHAPTER_CATEGORIES",
    "CAN_IGNORE_CATEGORIES",
    "AUTO_SUPPRESS_CATEGORIES",
    "PERSISTS_IGNORE_CATEGORIES",
    "filter_persistent_ignores",
]
