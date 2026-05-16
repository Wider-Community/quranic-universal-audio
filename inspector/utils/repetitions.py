"""Repetition-segment helpers.

A repetition segment is one where the reciter went back and re-read part of
the matched span. The pipeline records the back-jumps as
``wrap_word_ranges`` on the segment — a list of 3-tuples
``(jump_to, jump_from, repeat_end)`` describing each re-read range. From
that we can reconstruct the *reading sequence* — the ordered list of
section refs as the reciter actually performed them — which is what we
hand to MFA to time-locate the boundary between consecutive passes.

The math is borrowed verbatim from
``.local/spaces/quranic_universal_aligner/src/core/segment_types.py`` —
ported so the inspector doesn't depend on the .local tree.
"""
from __future__ import annotations

from typing import Iterable


def compute_reading_sequence(ref_from: str, ref_to: str,
                             wrap_word_ranges: list) -> list[list[str]]:
    """Return ``[[from1, to1], [from2, to2], ...]`` reading-order sections.

    Each entry is a single contiguous span the reciter read. With a wrap
    list of 3-tuples ``(jump_to, jump_from, repeat_end)`` the output is:

      - forward pass: ``[ref_from, wraps[0].jump_from]``
      - then each wrap's actual span: ``[wrap.jump_to, wrap.repeat_end]``

    Legacy 2-tuple wrap data is supported but produces non-overlapping
    sections instead of true repeats.
    """
    if not wrap_word_ranges:
        return [[ref_from, ref_to]]

    if len(wrap_word_ranges[0]) >= 3:
        sections: list[list[str]] = [[ref_from, wrap_word_ranges[0][1]]]
        for wr in wrap_word_ranges:
            sections.append([wr[0], wr[2]])
        return sections

    sections = [[ref_from, wrap_word_ranges[0][1]]]
    for i in range(len(wrap_word_ranges) - 1):
        sections.append([wrap_word_ranges[i][0], wrap_word_ranges[i + 1][1]])
    sections.append([wrap_word_ranges[-1][0], ref_to])
    return sections


def _parse_word_ref(ref: str) -> tuple[int, int, int] | None:
    """Parse ``"surah:ayah:word"`` → ``(surah, ayah, word)``. None on malform."""
    parts = ref.split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None


def count_words_in_section(ref_from: str, ref_to: str,
                           verse_word_counts: dict[tuple[int, int], int]) -> int:
    """Count words in the inclusive range ``ref_from..ref_to``.

    ``verse_word_counts`` is keyed by ``(surah, ayah)`` (the same shape
    ``services.data_loader.get_word_counts`` returns). Multi-verse sections
    walk verse-by-verse using the count map; an unknown verse contributes 0
    (caller's responsibility to handle pathologically short sections).
    """
    a = _parse_word_ref(ref_from)
    b = _parse_word_ref(ref_to)
    if not a or not b or a[0] != b[0]:
        return 0
    surah = a[0]
    if a[1] == b[1]:
        return max(0, b[2] - a[2] + 1)
    total = (verse_word_counts.get((surah, a[1]), 0) - a[2] + 1)
    for ayah in range(a[1] + 1, b[1]):
        total += verse_word_counts.get((surah, ayah), 0)
    total += b[2]
    return max(0, total)


def section_refs_canonical(sections: Iterable[list[str]]) -> list[str]:
    """Turn ``[[from, to], ...]`` into canonical compound refs ``"from-to"``."""
    return [f"{f}-{t}" for f, t in sections]


# ---------------------------------------------------------------------------
# Wrap-geometry validation (shared by save_payload + the cleanup script)
# ---------------------------------------------------------------------------

def _word_position(t: tuple[int, int, int],
                   verse_word_counts: dict[tuple[int, int], int]) -> int | None:
    """Linear word position within the surah (1-based across all verses).

    Returns ``None`` when any verse along the way isn't in the counts map —
    callers treat that as "opaque, leave alone" rather than a failure.
    """
    surah, ayah, word = t
    pos = 0
    for a in range(1, ayah):
        n = verse_word_counts.get((surah, a))
        if n is None:
            return None
        pos += n
    return pos + word


def is_wrap_consistent(matched_ref: str, wrap: list,
                       verse_word_counts: dict[tuple[int, int], int]) -> bool:
    """True iff ``wrap`` is geometrically valid for ``matched_ref``.

    Two failure modes are caught:

    - **stale**: any wrap word position falls outside ``matched_ref``'s
      surah word range (the post-split-inheritance leak).
    - **corrupted**: wrap geometry is internally inconsistent
      (``jump_from < jump_to`` — would be a forward jump, not a back-jump,
      or ``repeat_end < jump_to`` — repeat ends before it starts).

    Returns ``True`` when the wrap looks consistent OR when any verse
    reference is opaque (unknown surah, unparseable ref) — callers keep the
    wrap in those cases rather than discard data based on uncertainty.
    """
    if not wrap:
        return True
    parts = matched_ref.split("-")
    if len(parts) != 2:
        return False
    rf = _parse_word_ref(parts[0])
    rt = _parse_word_ref(parts[1])
    if not rf or not rt or rf[0] != rt[0]:
        return False
    surah = rf[0]
    rf_pos = _word_position(rf, verse_word_counts)
    rt_pos = _word_position(rt, verse_word_counts)
    if rf_pos is None or rt_pos is None:
        return True  # opaque — don't discard

    for w in wrap:
        if not isinstance(w, (list, tuple)) or len(w) < 3:
            return False
        wt = _parse_word_ref(w[0])
        wf = _parse_word_ref(w[1])
        we = _parse_word_ref(w[2])
        if not wt or not wf or not we:
            return False
        if wt[0] != surah or wf[0] != surah or we[0] != surah:
            return False
        wt_pos = _word_position(wt, verse_word_counts)
        wf_pos = _word_position(wf, verse_word_counts)
        we_pos = _word_position(we, verse_word_counts)
        if wt_pos is None or wf_pos is None or we_pos is None:
            return True  # opaque — don't discard
        if wf_pos < wt_pos or we_pos < wt_pos:
            return False  # corrupted geometry
        for p in (wt_pos, wf_pos, we_pos):
            if p < rf_pos or p > rt_pos:
                return False  # stale (outside matched_ref)
    return True
