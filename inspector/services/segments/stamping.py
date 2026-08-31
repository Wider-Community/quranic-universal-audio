"""Persisted classifier-field stamping — one implementation for every writer.

``qalqala_letter`` and ``is_boundary_adj`` are persisted on each segment so the
validate pass reads them instead of recomputing per request. Both are pure
functions of ``matched_ref`` plus reference data, so a writer that rewrites a
ref must re-stamp, and re-stamping an unchanged segment yields the same values.

Two writers stamp through here: the live save path, segment by segment as an
edit rewrites a ref (``services/segments/save.py``), and the pipeline-run
promoter, whole entries at once.

``is_boundary_adj`` is computed structural-only (``canonical=None``): the
phonemic side was retired in Migration #5 and ``compute_is_boundary_adj``
ignores the argument.
"""

from __future__ import annotations

from services.segments.qalqala import compute_qalqala_letter
from services.storage.data_loader import get_single_word_verses
from services.validation.classifier import compute_is_boundary_adj

# A boundary-rule ``matched_ref`` is ``<surah>:<ayah>:<word>-<surah>:<ayah>:<word>``.
# Anything else — a special transition token, an empty ref — carries no rule.
_REF_ENDPOINTS = 2
_LOCATION_PARTS = 3


def stamp_segment(seg: dict, single_word_verses: set) -> None:
    """Stamp ``qalqala_letter`` and ``is_boundary_adj`` onto *seg* in place."""
    seg["qalqala_letter"] = compute_qalqala_letter(seg)
    seg["is_boundary_adj"] = _boundary_adj(seg, single_word_verses)


def stamp_entries(
    entries: list[dict],
    *,
    word_counts: dict | None = None,
    single_word_verses: set | None = None,
) -> int:
    """Stamp every segment of every entry in *entries*; return the count stamped.

    ``single_word_verses`` is used as given; otherwise it is derived from
    ``word_counts``; otherwise it comes from the cached reference loader.
    """
    if single_word_verses is None:
        single_word_verses = (
            get_single_word_verses()
            if word_counts is None
            else {ref for ref, count in word_counts.items() if count == 1}
        )

    stamped = 0
    for entry in entries:
        for seg in entry.get("segments", []):
            stamp_segment(seg, single_word_verses)
            stamped += 1
    return stamped


def _boundary_adj(seg: dict, single_word_verses: set) -> bool:
    """The structural boundary-adjustment value for *seg*.

    ``False`` whenever ``matched_ref`` is not a parseable word range — the rule
    needs the surah, the start ayah and both word positions.
    """
    endpoints = (seg.get("matched_ref") or "").split("-")
    if len(endpoints) != _REF_ENDPOINTS:
        return False
    start = endpoints[0].split(":")
    end = endpoints[1].split(":")
    if len(start) != _LOCATION_PARTS or len(end) != _LOCATION_PARTS:
        return False
    try:
        surah = int(start[0])
        s_ayah = int(start[1])
        s_word = int(start[2])
        e_word = int(end[2])
    except ValueError:
        return False
    return compute_is_boundary_adj(seg, surah, s_ayah, s_word, e_word, single_word_verses, None)
