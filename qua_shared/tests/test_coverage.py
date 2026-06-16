"""Tests for the concise coverage-gap notation (``qua_shared/coverage.py``).

Guards the split contract — whole missing surahs vs within-surah verse gaps —
and the run-collapsing format, using the real shapes the v2.0.0 cut produces.
"""

from __future__ import annotations

from qua_shared.coverage import _compress_ints, missing_coverage, verse_counts_from_surah_info

# A tiny mushaf: surah 1 (3 verses), surah 2 (5), surah 3 (4).
_COUNTS = {1: 3, 2: 5, 3: 4}


def _all(counts):
    return {(s, a) for s, n in counts.items() for a in range(1, n + 1)}


def test_compress_ints_collapses_consecutive_runs():
    assert _compress_ints([4, 7, 9, 37, 39, 40, 45, 65]) == "4,7,9,37,39-40,45,65"
    assert _compress_ints([18, 19, 20, 40]) == "18-20,40"
    assert _compress_ints([5]) == "5"
    assert _compress_ints([]) == ""


def test_complete_recitation_has_no_gaps():
    assert missing_coverage(_all(_COUNTS), _COUNTS) == ("", "")


def test_whole_missing_surah_goes_to_missing_surahs_only():
    present = _all(_COUNTS) - {(2, a) for a in range(1, 6)}  # drop all of surah 2
    surahs, verses = missing_coverage(present, _COUNTS)
    assert surahs == "2"
    assert verses == ""


def test_within_surah_gap_goes_to_missing_verses_only():
    present = _all(_COUNTS) - {(2, 3), (3, 1)}
    surahs, verses = missing_coverage(present, _COUNTS)
    assert surahs == ""
    assert verses == "2:3, 3:1"


def test_runs_inside_a_surah_collapse():
    present = _all(_COUNTS) - {(2, 2), (2, 3), (2, 4)}
    surahs, verses = missing_coverage(present, _COUNTS)
    assert surahs == ""
    assert verses == "2:2-4"


def test_whole_and_partial_partition_the_gap():
    present = _all(_COUNTS) - {(2, a) for a in range(1, 6)} - {(3, 4)}
    surahs, verses = missing_coverage(present, _COUNTS)
    assert surahs == "2"
    assert verses == "3:4"


def test_verse_counts_from_surah_info():
    surah_info = {
        "1": {"num_verses": 7, "verses": []},
        "2": {"num_verses": 286, "verses": []},
    }
    assert verse_counts_from_surah_info(surah_info) == {1: 7, 2: 286}
