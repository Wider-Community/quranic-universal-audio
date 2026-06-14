"""Mushaf coverage gaps for a recitation, in concise notation.

Given the verses a recitation actually covers, derive what's missing vs the full
mushaf and render it compactly for the release ``catalog.json`` + the changelog
table. Whole missing surahs and within-surah verse gaps are split into two
strings so even a partial recitation (e.g. a Juz' ʿAmma reciter) stays concise.
Shared by ``qua_jobs/cut_release.py`` for both the catalog field and the
changelog member rows, so the JSON and the human table can't drift.
"""

from __future__ import annotations

from collections.abc import Iterable


def verse_counts_from_surah_info(surah_info: dict) -> dict[int, int]:
    """``{surah: num_verses}`` from a loaded surah_info dict."""
    return {int(s): int(info["num_verses"]) for s, info in surah_info.items()}


def _compress_ints(nums: Iterable[int]) -> str:
    """Collapse ints into comma-separated ascending runs: ``1-3,5,7-9``."""
    ordered = sorted(set(nums))
    if not ordered:
        return ""
    runs: list[str] = []
    start = prev = ordered[0]
    for n in ordered[1:]:
        if n == prev + 1:
            prev = n
            continue
        runs.append(f"{start}-{prev}" if start != prev else f"{start}")
        start = prev = n
    runs.append(f"{start}-{prev}" if start != prev else f"{start}")
    return ",".join(runs)


def missing_coverage(
    present: Iterable[tuple[int, int]], surah_verse_counts: dict[int, int]
) -> tuple[str, str]:
    """Return ``(missing_surahs, missing_verses)`` for a recitation.

    ``present`` is the ``(surah, ayah)`` the recitation covers;
    ``surah_verse_counts`` is ``{surah: num_verses}`` for the full mushaf.

    - ``missing_surahs`` — surahs with ZERO covered verses, as compact ascending
      runs of surah numbers (``"1-84"``, ``"4,7,9,37,39-40,45,65"``).
    - ``missing_verses`` — within-surah gaps only (a surah that IS partly
      covered), as ``surah:ayah`` runs, surahs joined by ``", "``
      (``"7:116, 41:15"``, ``"2:30,32-34, 5:11"``, ``"75:18-40"``).

    Both are ``""`` when nothing is missing in that category. A whole missing
    surah never appears in ``missing_verses`` and vice-versa, so the two strings
    partition the gap and each stays short.
    """
    present_by_surah: dict[int, set[int]] = {}
    for surah, ayah in present:
        present_by_surah.setdefault(int(surah), set()).add(int(ayah))

    whole_missing: list[int] = []
    partial_parts: list[str] = []
    for surah in sorted(surah_verse_counts):
        covered = present_by_surah.get(surah, set())
        if not covered:
            whole_missing.append(surah)
            continue
        gaps = set(range(1, surah_verse_counts[surah] + 1)) - covered
        if gaps:
            partial_parts.append(f"{surah}:{_compress_ints(gaps)}")
    return _compress_ints(whole_missing), ", ".join(partial_parts)
