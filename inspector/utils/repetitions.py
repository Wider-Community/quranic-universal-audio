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
