"""Word-by-word timing coverage for a sample.

A sample earns the "WBW Timestamps" tag when every Quran-ref segment carries a
word timing for each word of its ref. Special segments (Basmala, Takbir, ...)
have no Quran words and are ignored; a sample with no Quran-ref segment at all
is not complete.

Mirrors the frontend rule in ``utils/samples/word-timings.ts`` so the tag and
the per-row realign trigger agree.
"""

from __future__ import annotations

from utils.repetitions import count_words_in_section


def _parse_location(location: str) -> tuple[int, int, int] | None:
    parts = location.split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None


def _span(matched_ref: str) -> tuple[str, str] | None:
    """``(ref_from, ref_to)`` for a Quran span, else ``None``."""
    if ":" not in matched_ref:
        return None
    ref_from, _, ref_to = matched_ref.partition("-")
    return ref_from, (ref_to or ref_from)


def segment_covered(seg: dict, word_counts: dict[tuple[int, int], int]) -> bool | None:
    """``True``/``False`` for a Quran-ref segment, ``None`` when not applicable."""
    span = _span(seg.get("matched_ref") or "")
    if span is None:
        return None
    ref_from, ref_to = span
    expected = count_words_in_section(ref_from, ref_to, word_counts)
    if expected <= 0:
        return None
    start, end = _parse_location(ref_from), _parse_location(ref_to)
    if start is None or end is None:
        return None
    covered = {
        w["location"]
        for w in (seg.get("word_timings") or [])
        if (key := _parse_location(str(w.get("location") or ""))) and start <= key <= end
    }
    return len(covered) >= expected


def is_wbw_complete(entries: list[dict], word_counts: dict[tuple[int, int], int]) -> bool:
    """True when every Quran-ref segment of ``entries`` is fully covered."""
    seen_quran = False
    for entry in entries:
        for seg in entry.get("segments", []):
            covered = segment_covered(seg, word_counts)
            if covered is None:
                continue
            if not covered:
                return False
            seen_quran = True
    return seen_quran
