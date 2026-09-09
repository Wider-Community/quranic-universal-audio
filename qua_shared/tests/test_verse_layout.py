"""The shared per-verse layout builder — the single geometry both release
channels consume. Locks: ratio-fit clip windows, occurrence-pinned byte-exact
segments (no overlap on a repeated pivot word), and the outer-edge override.
"""

from __future__ import annotations

from qua_shared.verse_layout import PadParams, build_verse_layouts

PADS: PadParams = {"pad_start": 100, "pad_end": 300, "min_gap": 100}


def _ts(words, vs, ve, seg_spans=None):
    return {
        "words": words,
        "word_texts": ["x"] * len(words),
        "tokens_by_word": [[] for _ in words],
        "verse_start_ms": vs,
        "verse_end_ms": ve,
        "seg_spans": seg_spans,
    }


def test_clip_window_full_pads_when_silence_is_ample():
    # 4000ms of silence between 1:1 and 1:2 — both get their full pads.
    timestamps = {
        "1:1": _ts([[1, 100, 1000]], 100, 1000),
        "1:2": _ts([[1, 5000, 6000]], 5000, 6000),
    }
    lay = build_verse_layouts(timestamps, **PADS)
    # 1:1 chapter-first: lead clamps to 0; tail = pad_end into the gap.
    assert lay["1:1"]["clip_start"] == 0
    assert lay["1:1"]["clip_end"] == 1300  # 1000 + 300
    # 1:2 chapter-last: lead = pad_start, tail = pad_end (no next).
    assert lay["1:2"]["clip_start"] == 4900  # 5000 - 100
    assert lay["1:2"]["clip_end"] == 6300  # 6000 + 300


def test_clip_window_ratio_fit_keeps_min_gap():
    # Only 300ms of silence: pads scale by ratio, leaving exactly min_gap.
    timestamps = {
        "1:1": _ts([[1, 100, 1000]], 100, 1000),
        "1:2": _ts([[1, 1300, 2000]], 1300, 2000),
    }
    lay = build_verse_layouts(timestamps, **PADS)
    end1 = lay["1:1"]["clip_end"]  # 1000 + 150 (3/4 of the 200 budget)
    start2 = lay["1:2"]["clip_start"]  # 1300 - 50  (1/4 of the 200 budget)
    assert end1 == 1150
    assert start2 == 1250
    assert start2 - end1 == 100  # == min_gap, no leak


def test_repeat_pivot_segments_non_overlapping_and_outer_override():
    # 2:6 shape: word 6 recited in both segments (look-back pivot). The
    # occurrence spans pin each segment to its own word-6, so segments stay
    # non-overlapping; the outer segments stretch to the clip edges.
    words = [
        [1, 70, 1020],
        [2, 1020, 1910],
        [3, 1910, 2660],
        [4, 2660, 4930],
        [5, 4930, 5860],
        [6, 5860, 8530],  # word 6, first occurrence
        [6, 8540, 10340],
        [7, 10340, 10700],
        [8, 10700, 11060],
        [9, 11060, 12740],
        [10, 12740, 13160],
        [11, 13160, 15280],
    ]
    seg_spans = [
        {
            "ref": "2:6",
            "w_from": 1,
            "w_to": 6,
            "occ_start": 0,
            "occ_end": 6,
            "start_ms": 70,
            "end_ms": 8530,
        },
        {
            "ref": "2:6",
            "w_from": 6,
            "w_to": 11,
            "occ_start": 6,
            "occ_end": 12,
            "start_ms": 8540,
            "end_ms": 15280,
        },
    ]
    lay = build_verse_layouts({"2:6": _ts(words, 70, 15280, seg_spans)}, **PADS)["2:6"]
    segs = lay["segments"]
    assert len(segs) == 2
    # seg A ends at the FIRST word-6 (8530); seg B starts at the SECOND (8540) →
    # non-overlapping (10ms = recovered silence between the two passes).
    assert segs[0][3] == 8530
    assert segs[1][2] == 8540
    assert segs[0][3] < segs[1][2]
    # Outer-edge override: first segment starts at clip_start, last ends at clip_end.
    assert segs[0][2] == lay["clip_start"]
    assert segs[-1][3] == lay["clip_end"]
