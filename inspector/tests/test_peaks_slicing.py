"""Tests for chapter-peaks slicing in ``routes/peaks._slice_chapter_peaks``.

Slicing is the perf win for the Segments tab: when the prefetch worker has
already written ``wip/<slug>/peaks/<chapter>.json``, segment-peaks requests
turn into an O(N) array slice instead of a fresh decode. The slice also
honours an optional pad so split / auto-split scrubbers show neighbour
samples beyond the segment boundary.
"""
from __future__ import annotations

from routes.peaks import _slice_chapter_peaks


def _make_chapter_peaks(num: int = 1000, duration_ms: int = 10_000):
    return {
        "duration_ms": duration_ms,
        "peaks": [[-i / num, i / num] for i in range(num)],
    }


def test_slice_returns_proportional_window():
    cp = _make_chapter_peaks(num=1000, duration_ms=10_000)
    out = _slice_chapter_peaks(cp, start_ms=2_000, end_ms=4_000, pad_ms=0)
    assert out["start_ms"] == 2_000
    assert out["end_ms"] == 4_000
    assert out["duration_ms"] == 2_000
    # 20%–40% of 1000 buckets = indices [200, 400).
    assert len(out["peaks"]) == 200
    assert out["peaks"][0] == cp["peaks"][200]
    assert out["peaks"][-1] == cp["peaks"][399]


def test_pad_clamps_at_start_and_end():
    cp = _make_chapter_peaks(num=100, duration_ms=10_000)

    # Pad would push start below zero — clamps to 0.
    out_lo = _slice_chapter_peaks(cp, start_ms=200, end_ms=500, pad_ms=1_000)
    assert out_lo["start_ms"] == 0
    assert out_lo["end_ms"] == 1_500

    # Pad would push end past duration — clamps to duration_ms.
    out_hi = _slice_chapter_peaks(cp, start_ms=9_500, end_ms=9_800, pad_ms=1_000)
    assert out_hi["start_ms"] == 8_500
    assert out_hi["end_ms"] == 10_000


def test_returns_none_when_chapter_peaks_missing_or_malformed():
    assert _slice_chapter_peaks(None, 0, 100, 0) is None
    assert _slice_chapter_peaks({"peaks": []}, 0, 100, 0) is None
    assert _slice_chapter_peaks({"duration_ms": 0, "peaks": [[0, 0]]}, 0, 100, 0) is None
    assert _slice_chapter_peaks({"duration_ms": 100, "peaks": "nope"}, 0, 50, 0) is None


def test_returns_none_when_window_collapses_after_clamp():
    cp = _make_chapter_peaks(num=100, duration_ms=10_000)
    # start_ms beyond chapter end → after clamp lo == hi → None.
    assert _slice_chapter_peaks(cp, start_ms=20_000, end_ms=21_000, pad_ms=0) is None
