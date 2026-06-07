"""build_rows: segment word-range (from matched_ref) + source_url (from manifest).

Regression guards for two corruptions: segments collapsing to ``[1,1,...]`` (no
word_from/word_to in detailed.json — the span lives in ``matched_ref``) and an
empty ``source_url`` (detailed.json has no per-entry ``audio`` field; the URL
comes from the audio manifest's chapter map).
"""

from __future__ import annotations

from qua_jobs.publish_hf import _detailed_by_ref, _seg_word_range, build_rows

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
