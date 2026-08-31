"""``missed_pause`` classification: interior stop-sign ه/ة words only.

Uses the real Digital Khatt data (same as the qalqala classifier tests):
2:2:4 ``رَيْبَۛ`` bears a stop sign but ends in ب (non-candidate);
2:2:5 ``فِيهِۛ`` bears a stop sign and ends in ه (candidate).
"""

from __future__ import annotations

from services.validation.classifier import classify_flags, classify_segment
from services.validation.detail import _build_detail_lists

CANDIDATE_LOC = "2:2:5"


def _classify(seg: dict) -> list[str]:
    return classify_segment(seg, entry_ref="2", is_by_ayah=False)


def _flags(seg: dict) -> dict:
    return classify_flags(
        seg,
        entry_ref="2",
        is_by_ayah=False,
        surah=2,
        s_ayah=2,
        e_ayah=2,
        s_word=int(seg["matched_ref"].split("-")[0].split(":")[2]),
        e_word=int(seg["matched_ref"].split("-")[1].split(":")[2]),
        single_word_verses=set(),
        canonical=None,
    )


def test_interior_candidate_word_flags_and_reports_loc():
    seg = {"matched_ref": "2:2:4-2:2:7", "confidence": 1.0}
    flags = _flags(seg)
    assert flags["missed_pause"] is True
    assert flags["missed_pause_words"] == [CANDIDATE_LOC]
    assert "missed_pause" in _classify(seg)


def test_candidate_word_at_segment_edges_does_not_flag():
    # Candidate as the range's FIRST word.
    first_edge = {"matched_ref": "2:2:5-2:2:7", "confidence": 1.0}
    assert _flags(first_edge)["missed_pause"] is False
    assert "missed_pause" not in _classify(first_edge)

    # Candidate as the range's LAST word.
    last_edge = {"matched_ref": "2:2:3-2:2:5", "confidence": 1.0}
    assert _flags(last_edge)["missed_pause"] is False
    assert "missed_pause" not in _classify(last_edge)


def test_interior_stop_sign_word_not_ending_ha_does_not_flag():
    # Interior word is 2:2:4 (stop sign, ends in ب) — not a candidate.
    seg = {"matched_ref": "2:2:3-2:2:5", "confidence": 1.0}
    flags = _flags(seg)
    assert flags["missed_pause"] is False
    assert flags["missed_pause_words"] == []


def test_ignored_categories_suppresses():
    seg = {
        "matched_ref": "2:2:4-2:2:7",
        "confidence": 1.0,
        "ignored_categories": ["missed_pause"],
    }
    flags = _flags(seg)
    assert flags["missed_pause"] is False
    assert flags["missed_pause_words"] == []
    assert "missed_pause" not in _classify(seg)


def test_two_word_segment_never_flags():
    seg = {"matched_ref": "2:2:4-2:2:5", "confidence": 1.0}
    assert _flags(seg)["missed_pause"] is False


def test_detail_item_carries_words_with_text_and_mark():
    entries = [
        {
            "ref": "2",
            "segments": [
                {
                    "segment_uid": "mp-1",
                    "matched_ref": "2:2:4-2:2:7",
                    "confidence": 1.0,
                    "time_start": 0,
                    "time_end": 4000,
                }
            ],
        }
    ]
    detail = _build_detail_lists(
        entries,
        is_by_ayah=False,
        word_counts={(2, 2): 7},
        canonical=None,
        single_word_verses=set(),
    )
    items = detail["missed_pause"]
    assert len(items) == 1
    item = items[0]
    assert item["segment_uid"] == "mp-1"
    assert item["ref"] == "2:2:4-2:2:7"
    assert item["time"] == "0:00-0:04"
    assert "missed_pause" in item["classified_issues"]
    assert len(item["words"]) == 1
    word = item["words"][0]
    assert word["ref"] == CANDIDATE_LOC
    assert word["mark"] == "ۛ"  # ۛ
    assert "ۛ" in word["text"]
