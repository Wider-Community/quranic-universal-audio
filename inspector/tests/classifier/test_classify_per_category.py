"""Per-category classifier tests, parametrized over fixtures.

Each test loads a fixture, runs the unified backend classifier, and
compares per-segment categories to the baseline in
``expected/<fixture>.classify.json``.
"""
from __future__ import annotations

import pytest

pytest.importorskip(
    "services.validation.classifier",
    reason="phase-2 — unified classifier not yet introduced",
)


FIXTURES = ["112-ikhlas", "113-falaq", "synthetic-structural", "synthetic-classifier"]


def _classify(seg: dict, **ctx) -> list[str]:
    from services.validation.classifier import classify_segment  # type: ignore
    return classify_segment(seg, **ctx)


@pytest.mark.parametrize("fixture_name", FIXTURES, ids=FIXTURES)
def test_each_category_classified_in_expected_segments(
    fixture_name, load_fixture, load_expected
):
    fixture = load_fixture(fixture_name)
    expected = load_expected(fixture_name, "classify")
    by_uid = expected["by_segment_uid"]

    from services.validation.classifier import classify_entry  # type: ignore

    for entry in fixture["entries"]:
        results = classify_entry(entry)
        for seg in entry["segments"]:
            uid = seg.get("segment_uid")
            if uid not in by_uid:
                continue
            actual = sorted(results.get(uid, {}).get("categories", []))
            want = sorted(by_uid[uid].get("categories", []))
            assert actual == want, (
                f"{fixture_name}::{uid}: expected categories {want!r}, got {actual!r}"
            )


def test_low_confidence_threshold_is_0_80():
    """Segments with confidence ∈ [0.79, 0.81] flip on/off correctly around 0.80."""
    base = {
        "matched_ref": "1:1:1-1:1:1",
        "matched_text": "x",
        "phonemes_asr": "",
    }
    below = _classify({**base, "confidence": 0.79}, entry_ref="1", is_by_ayah=False)
    on_threshold = _classify({**base, "confidence": 0.80}, entry_ref="1", is_by_ayah=False)
    above = _classify({**base, "confidence": 0.81}, entry_ref="1", is_by_ayah=False)

    assert "low_confidence" in below
    assert "low_confidence" not in on_threshold
    assert "low_confidence" not in above


def test_low_confidence_detail_threshold_is_1_00():
    """Segments with confidence < 1.00 fall in the detail tier; confidence == 1.00 do not."""
    base = {
        "matched_ref": "1:1:1-1:1:1",
        "matched_text": "x",
        "phonemes_asr": "",
    }
    just_below = _classify(
        {**base, "confidence": 0.999}, entry_ref="1", is_by_ayah=False, detail=True
    )
    perfect = _classify(
        {**base, "confidence": 1.00}, entry_ref="1", is_by_ayah=False, detail=True
    )

    assert "low_confidence_detail" in just_below
    assert "low_confidence_detail" not in perfect


def test_audio_bleeding_uses_seg_belongs_to_entry():
    """Fixture segment with entry_ref 1:1 + matched_ref 1:2:1 flips audio_bleeding=true."""
    seg = {
        "matched_ref": "1:2:1-1:2:1",
        "matched_text": "x",
        "phonemes_asr": "",
        "confidence": 1.0,
    }
    result = _classify(seg, entry_ref="1:1", is_by_ayah=True)
    assert "audio_bleeding" in result


def test_repetitions_only_wrap_word_ranges():
    """Segment with has_repeated_words=true but no wrap_word_ranges does NOT classify as repetitions (tie-breaker B-1)."""
    seg = {
        "matched_ref": "1:1:1-1:1:1",
        "matched_text": "x",
        "phonemes_asr": "",
        "confidence": 1.0,
        "has_repeated_words": True,
    }
    result = _classify(seg, entry_ref="1", is_by_ayah=False)
    assert "repetitions" not in result, (
        "has_repeated_words alone should not classify as repetitions; wrap_word_ranges is required (see bug-log B-1)"
    )

    seg_with_wrap = dict(seg, wrap_word_ranges=[[1, 1]])
    result2 = _classify(seg_with_wrap, entry_ref="1", is_by_ayah=False)
    assert "repetitions" in result2


def test_boundary_adj_phoneme_tail_optional():
    """Segment qualifying for boundary_adj: with canonical phonemes provided, tail-mismatch may flip."""
    seg = {
        "matched_ref": "1:6:1-1:6:1",
        "matched_text": "x",
        "phonemes_asr": "a b c",
        "confidence": 1.0,
    }
    plain = _classify(seg, entry_ref="1", is_by_ayah=False, canonical=None)
    assert "boundary_adj" in plain or "boundary_adj" not in plain


def test_qalqala_letter_field_populated():
    """Qalqala-classified segment carries a qalqala_letter field with the actual final letter."""
    from services.validation.classifier import classify_segment_full  # type: ignore

    seg = {
        "matched_ref": "112:1:1-112:1:4",
        "matched_text": "أَحَدٌ",
        "phonemes_asr": "",
        "confidence": 1.0,
    }
    result = classify_segment_full(seg, entry_ref="112", is_by_ayah=False)
    assert "qalqala" in result.get("categories", [])
    assert result.get("qalqala_letter") == "د"


def test_muqattaat_only_first_word_of_verse():
    """A muqattaat verse with s_word=2 does NOT classify; s_word=1 does."""
    base_seg = {
        "matched_text": "x",
        "phonemes_asr": "",
        "confidence": 1.0,
    }
    word1 = dict(base_seg, matched_ref="2:1:1-2:1:1")
    word2 = dict(base_seg, matched_ref="2:1:2-2:1:2")

    r1 = _classify(word1, entry_ref="2", is_by_ayah=False)
    r2 = _classify(word2, entry_ref="2", is_by_ayah=False)

    assert "muqattaat" in r1
    assert "muqattaat" not in r2


def test_basmala_amin_detail_uses_last_segment_overlapping_1_7():
    """Basmala + Amin shows 1:1 plus only the latest card overlapping 1:7."""
    from services.validation.detail import _build_detail_lists  # type: ignore

    entries = [{
        "ref": "1",
        "segments": [
            {
                "segment_uid": "one-one",
                "matched_ref": "1:1:1-1:1:1",
                "matched_text": "x",
                "phonemes_asr": "",
                "confidence": 1.0,
                "time_start": 0,
                "time_end": 1000,
            },
            {
                "segment_uid": "one-seven-a",
                "matched_ref": "1:7:1-1:7:2",
                "matched_text": "x",
                "phonemes_asr": "",
                "confidence": 1.0,
                "time_start": 1000,
                "time_end": 2000,
            },
            {
                "segment_uid": "one-seven-b",
                "matched_ref": "1:7:3-1:7:4",
                "matched_text": "x",
                "phonemes_asr": "",
                "confidence": 1.0,
                "time_start": 2000,
                "time_end": 3000,
            },
        ],
    }]

    detail = _build_detail_lists(
        entries,
        is_by_ayah=False,
        word_counts={(1, 1): 1, (1, 7): 4},
        canonical=None,
        single_word_verses=set(),
    )

    assert [item["segment_uid"] for item in detail["basmala_amin"]] == [
        "one-one",
        "one-seven-b",
    ]


def test_basmala_amin_detail_omits_neighboring_fatiha_verses():
    """The accordion includes 1:1 and 1:7 but not 1:2 through 1:6."""
    from services.validation.detail import _build_detail_lists  # type: ignore

    entries = [{
        "ref": "1",
        "segments": [
            {
                "segment_uid": f"one-{ayah}",
                "matched_ref": f"1:{ayah}:1-1:{ayah}:1",
                "matched_text": "x",
                "phonemes_asr": "",
                "confidence": 1.0,
                "time_start": ayah * 1000,
                "time_end": (ayah + 1) * 1000,
            }
            for ayah in range(1, 8)
        ],
    }]

    detail = _build_detail_lists(
        entries,
        is_by_ayah=False,
        word_counts={(1, ayah): 1 for ayah in range(1, 8)},
        canonical=None,
        single_word_verses=set(),
    )

    assert [item["segment_uid"] for item in detail["basmala_amin"]] == ["one-1", "one-7"]
