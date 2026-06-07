"""build_rows: segment word-range (from matched_ref) + source_url (from manifest).

Regression guards for two corruptions: segments collapsing to ``[1,1,...]`` (no
word_from/word_to in detailed.json — the span lives in ``matched_ref``) and an
empty ``source_url`` (detailed.json has no per-entry ``audio`` field; the URL
comes from the audio manifest's chapter map).
"""

from __future__ import annotations

from qua_jobs.publish_hf import (
    _detailed_by_ref,
    _rebase_row_multi,
    _seg_word_range,
    _subtract_spans,
    build_rows,
)

_SURAH_INFO = {"1": {"verses": [{"verse": 1, "num_words": 4}, {"verse": 2, "num_words": 3}]}}


def test_seg_word_range_single_ayah():
    assert _seg_word_range("1:1:1-1:1:4", "1", 1, _SURAH_INFO) == (1, 4)
    assert _seg_word_range("1:2:2-1:2:3", "1", 2, _SURAH_INFO) == (2, 3)


def test_seg_word_range_cross_verse_clips_to_ayah():
    # Segment spans 1:1 word 3 -> 1:2 word 2.
    assert _seg_word_range("1:1:3-1:2:2", "1", 1, _SURAH_INFO) == (3, 4)  # to end of 1:1
    assert _seg_word_range("1:1:3-1:2:2", "1", 2, _SURAH_INFO) == (1, 2)  # from start of 1:2


def test_seg_word_range_non_overlapping_is_none():
    assert _seg_word_range("1:2:1-1:2:3", "1", 1, _SURAH_INFO) is None
    assert _seg_word_range("", "1", 1, _SURAH_INFO) is None


def test_build_rows_segments_and_source_url():
    detailed = {
        "entries": [
            {
                "ref": "1",
                "segments": [
                    {"time_start": 0, "time_end": 4000, "matched_ref": "1:1:1-1:1:4"},
                ],
            }
        ]
    }
    timestamps = {
        "1:1": {
            "words": [[1, 0, 1000], [2, 1000, 2000], [3, 2000, 3000], [4, 3000, 4000]],
            "letters": [],
            "verse_start_ms": 0,
            "verse_end_ms": 4000,
        }
    }
    rows = build_rows(
        timestamps,
        _detailed_by_ref(detailed),
        _SURAH_INFO,
        {},
        {"1": "https://cdn.example/001.mp3"},
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["source_url"] == "https://cdn.example/001.mp3"
    # Word span 1->4 (basmala), NOT the collapsed [1, 1].
    assert row["segments"][0][0] == 1
    assert row["segments"][0][1] == 4


# ---------------------------------------------------------------------------
# Interior no-match audio excision: keep_runs + piecewise rebase + full drop.
# ---------------------------------------------------------------------------


def test_subtract_spans_no_gap_is_single_run():
    assert _subtract_spans(0, 4000, []) == [(0, 4000)]
    # A span outside the window is ignored.
    assert _subtract_spans(0, 4000, [(5000, 6000)]) == [(0, 4000)]


def test_subtract_spans_interior_and_overlapping():
    assert _subtract_spans(0, 4000, [(2000, 3000)]) == [(0, 2000), (3000, 4000)]
    # Overlapping / out-of-order spans are clipped + merged.
    assert _subtract_spans(0, 4000, [(2500, 3000), (2000, 2600)]) == [(0, 2000), (3000, 4000)]
    # Span clipped to the window edges.
    assert _subtract_spans(0, 4000, [(-100, 500)]) == [(500, 4000)]


def _ts(words, start, end):
    return {"words": words, "letters": [], "verse_start_ms": start, "verse_end_ms": end}


def test_build_rows_keep_runs_contiguous_single_run():
    # No no-match segment → one run spanning the whole verse (today's behavior).
    detailed = {
        "entries": [
            {
                "ref": "1:1",
                "segments": [{"time_start": 0, "time_end": 4000, "matched_ref": "1:1:1-1:1:4"}],
            }
        ]
    }
    timestamps = {
        "1:1": _ts([[1, 0, 1000], [2, 1000, 2000], [3, 2000, 3000], [4, 3000, 4000]], 0, 4000)
    }
    rows = build_rows(timestamps, _detailed_by_ref(detailed), _SURAH_INFO, {}, {"1": "u"})
    assert rows[0]["keep_runs"] == [(0, 4000)]


def test_build_rows_keep_runs_interior_no_match_splits():
    # A no-match middle segment ([2000,3000], empty matched_ref) splits the clip
    # into two kept runs so the slicer can excise the gap audio.
    detailed = {
        "entries": [
            {
                "ref": "1:1",
                "segments": [
                    {"time_start": 0, "time_end": 2000, "matched_ref": "1:1:1-1:1:2"},
                    {"time_start": 2000, "time_end": 3000, "matched_ref": ""},  # no-match
                    {"time_start": 3000, "time_end": 4000, "matched_ref": "1:1:3-1:1:4"},
                ],
            }
        ]
    }
    timestamps = {
        "1:1": _ts([[1, 0, 1000], [2, 1000, 2000], [3, 3000, 3500], [4, 3500, 4000]], 0, 4000)
    }
    rows = build_rows(timestamps, _detailed_by_ref(detailed), _SURAH_INFO, {}, {"1": "u"})
    assert len(rows) == 1
    assert rows[0]["keep_runs"] == [(0, 2000), (3000, 4000)]


def test_build_rows_full_verse_no_match_drops_row():
    # 1:2's only segment is no-match → the projection never emits 1:2, so it's
    # absent from timestamps → no row built (point 2: full-verse drop).
    detailed = {
        "entries": [
            {
                "ref": "1:1",
                "segments": [{"time_start": 0, "time_end": 4000, "matched_ref": "1:1:1-1:1:4"}],
            },
            {"ref": "1:2", "segments": [{"time_start": 4000, "time_end": 6000, "matched_ref": ""}]},
        ]
    }
    timestamps = {
        "1:1": _ts([[1, 0, 1000], [2, 1000, 2000], [3, 2000, 3000], [4, 3000, 4000]], 0, 4000)
    }
    rows = build_rows(timestamps, _detailed_by_ref(detailed), _SURAH_INFO, {}, {"1": "u"})
    assert [(r["surah"], r["ayah"]) for r in rows] == [(1, 1)]


def test_rebase_row_multi_excises_gap_gaplessly():
    from qua_shared.mp3_frames import RunMap

    # Verse clip [0,4000] source; word 3 has a 1000 ms phantom gap before it
    # (the excised no-match audio at [2000,3000]).
    row = {
        "clip_start": 0,
        "clip_end": 4000,
        "duration_ms": 4000,
        "word_timestamps": [[1, 0, 1000], [2, 1000, 2000], [3, 3000, 3500], [4, 3500, 4000]],
        "segments": [[1, 2, 0, 2000], [3, 4, 3000, 4000]],
        "letter_timestamps": [{"word_idx": 3, "char": "x", "start_ms": 3000, "end_ms": 3100}],
    }
    # Runs: [0,2000) then [3000,4000) placed right after (cum_offset 2000).
    runs = [RunMap(0, 2000, 0), RunMap(3000, 4000, 2000)]
    _rebase_row_multi(row, runs)
    assert row["duration_ms"] == 3000
    assert row["clip_start"] == 0
    assert row["clip_end"] == 3000
    # Word 3 now starts exactly at word 2's end (2000) — the gap is gone.
    assert row["word_timestamps"] == [
        [1, 0, 1000],
        [2, 1000, 2000],
        [3, 2000, 2500],
        [4, 2500, 3000],
    ]
    assert row["segments"] == [[1, 2, 0, 2000], [3, 4, 2000, 3000]]
    assert row["letter_timestamps"][0]["start_ms"] == 2000
    assert row["letter_timestamps"][0]["end_ms"] == 2100
