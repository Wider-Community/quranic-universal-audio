"""Tests for services.auto_split — unified compute_auto_split contract.

Stubs the MFA HTTP client and ffmpeg invocation so we exercise:
- cross-verse N-cursor split (2-, 3-, 4-verse) + per-verse refs
- repetition reading-sequence boundary detection + N-way refs
- silent-fallback shape (even cuts) on MFA/ffmpeg failure
without any network or binary dependency.
"""
from __future__ import annotations

import pytest

from services import audio_source, auto_split
from utils.references import cross_verse_sections


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_is_cross_verse():
    assert auto_split._is_cross_verse("37:151:3-37:152:2")
    assert not auto_split._is_cross_verse("1:1:1-1:1:4")
    assert not auto_split._is_cross_verse("garbage")


def test_repetition_cuts_walks_section_word_counts():
    """Reading sequence [3 words][3 words] → one cut after word 3."""
    words = [
        {"location": "1:1:1", "start": 0.0, "end": 0.4},
        {"location": "1:1:2", "start": 0.5, "end": 0.9},
        {"location": "1:1:3", "start": 1.0, "end": 1.4},  # last of forward
        {"location": "1:1:2", "start": 1.6, "end": 2.0},  # repeat starts
        {"location": "1:1:3", "start": 2.1, "end": 2.5},
        {"location": "1:1:4", "start": 2.6, "end": 3.0},
    ]
    # midpoint(1.4, 1.6) = 1.5 s → 1500 ms
    assert auto_split._repetition_cuts(words, [3, 3]) == [1500]


def test_cross_verse_sections_two_verses():
    word_counts = {(37, 151): 39, (37, 152): 26}
    assert cross_verse_sections("37:151:3-37:152:2", word_counts) == [
        ["37:151:3", "37:151:39"],
        ["37:152:1", "37:152:2"],
    ]


def test_cross_verse_sections_three_verses():
    """3-verse seg: first partial, middle full, last partial."""
    word_counts = {(37, 1): 7, (37, 2): 3, (37, 3): 5}
    assert cross_verse_sections("37:1:1-37:3:2", word_counts) == [
        ["37:1:1", "37:1:7"],
        ["37:2:1", "37:2:3"],
        ["37:3:1", "37:3:2"],
    ]


def test_cross_verse_sections_missing_intermediate_word_count():
    """Middle verse total absent → None (no clean way to enumerate words)."""
    word_counts = {(37, 1): 7, (37, 3): 5}  # missing (37, 2)
    assert cross_verse_sections("37:1:1-37:3:2", word_counts) is None


def test_cross_verse_sections_cross_surah_returns_none():
    word_counts = {(1, 7): 3, (2, 1): 4}
    assert cross_verse_sections("1:7:1-2:1:3", word_counts) is None


def test_cross_verse_sections_same_verse_returns_none():
    word_counts = {(1, 1): 7}
    assert cross_verse_sections("1:1:1-1:1:4", word_counts) is None


# ---------------------------------------------------------------------------
# compute_auto_split — cross-verse
# ---------------------------------------------------------------------------

def _patch_seg(monkeypatch, seg):
    monkeypatch.setattr(auto_split, "_find_segment",
                        lambda *_a, **_k: {**seg, "_audio_url": "http://a"})
    monkeypatch.setattr(auto_split, "_slice_to_wav", lambda *_a, **_k: True)
    monkeypatch.setattr(auto_split, "get_word_counts",
                        lambda: {(37, 151): 39, (37, 152): 26, (1, 1): 7})
    # Pretend the chapter is prefetched on the bucket so _run_mfa proceeds
    # past the local-bytes guard. Tests that want the no-audio path replace
    # this stub themselves.
    monkeypatch.setattr(
        auto_split.audio_source, "resolve",
        lambda *_a, **_k: audio_source.AudioSource(
            cdn_url="http://a", data=b"\x00\x00", path=None,
            vbr=False, bitrate_kbps=None, chapter_key="1",
        ),
    )


def test_cross_verse_happy_path(monkeypatch):
    """2-verse seg → 1 cursor + 2 refs. Regression for the legacy shape."""
    seg = {"segment_uid": "u1", "matched_ref": "37:151:3-37:152:2",
           "time_start": 10_000, "time_end": 14_000, "confidence": 0.9}
    _patch_seg(monkeypatch, seg)
    monkeypatch.setattr(auto_split, "build_mfa_ref", lambda s: s["matched_ref"])
    monkeypatch.setattr(auto_split, "mfa_upload_and_submit",
                        lambda *a, **k: ("evt", {}, "http://mfa"))
    # section_word_counts for 37:151:3-37:151:39 = 37 words, 37:152:1-37:152:2
    # = 2 words → MFA must return 39 words in reading order. Only the last
    # word of section 1 and the first of section 2 matter for the cursor.
    s1_words = [
        {"location": f"37:151:{w}", "start": 0.05 * w, "end": 0.05 * w + 0.04}
        for w in range(3, 40)
    ]
    s2_words = [
        {"location": "37:152:1", "start": 1.60, "end": 1.90},
        {"location": "37:152:2", "start": 2.00, "end": 2.40},
    ]
    # Force last word of section 1 to end at 1.40 so midpoint(1.40,1.60)=1.50.
    s1_words[-1]["end"] = 1.40
    monkeypatch.setattr(auto_split, "mfa_wait_result", lambda *a, **k: [{
        "words": s1_words + s2_words,
    }])
    out = auto_split.compute_auto_split("r", 37, "u1")
    # midpoint(1.40, 1.60) = 1.50 s → seg-relative 1500 ms; absolute 11_500.
    assert out == {
        "cursors": [11_500],
        "refs": ["37:151:3-37:151:39", "37:152:1-37:152:2"],
        "kind": "cross_verse",
        "source": "mfa",
    }


def test_cross_verse_fallback_on_mfa_error(monkeypatch):
    """MFA dies → evenly-spaced cuts. For N=2 the single cut sits at midpoint."""
    seg = {"segment_uid": "u1", "matched_ref": "37:151:3-37:152:2",
           "time_start": 10_000, "time_end": 14_000, "confidence": 0.9}
    _patch_seg(monkeypatch, seg)
    monkeypatch.setattr(auto_split, "build_mfa_ref", lambda s: s["matched_ref"])

    def _boom(*_a, **_k):
        raise RuntimeError("MFA Space 500")

    monkeypatch.setattr(auto_split, "mfa_upload_and_submit", _boom)
    out = auto_split.compute_auto_split("r", 37, "u1")
    assert out["kind"] == "cross_verse"
    assert out["source"] == "fallback"
    # N=2 → 1 evenly-spaced cursor at seg midpoint.
    assert out["cursors"] == [12_000]
    assert out["refs"] == ["37:151:3-37:151:39", "37:152:1-37:152:2"]


def test_cross_verse_3_verses_happy_path(monkeypatch):
    """3-verse seg: 7+3+2=12 words in MFA output → 2 cursors + 3 refs."""
    seg = {"segment_uid": "u1", "matched_ref": "37:1:1-37:3:2",
           "time_start": 10_000, "time_end": 16_000, "confidence": 0.9}
    _patch_seg(monkeypatch, seg)
    # Override word_counts so cross_verse_sections produces (7, 3, 5) totals.
    monkeypatch.setattr(auto_split, "get_word_counts",
                        lambda: {(37, 1): 7, (37, 2): 3, (37, 3): 5})
    monkeypatch.setattr(auto_split, "build_mfa_ref", lambda s: s["matched_ref"])
    monkeypatch.setattr(auto_split, "mfa_upload_and_submit",
                        lambda *a, **k: ("evt", {}, "http://mfa"))
    # 7 words verse 1, 3 words verse 2, 2 words verse 3 (partial). Section
    # boundaries: between words 7-8 (mid 1.40-1.60 → 1.50s) and 10-11 (mid
    # 2.40-2.60 → 2.50s).
    words = (
        # verse 1 (7 words)
        [{"location": f"37:1:{i+1}", "start": 0.10 * i, "end": 0.10 * i + 0.08}
         for i in range(6)]
        + [{"location": "37:1:7", "start": 1.30, "end": 1.40}]
        # verse 2 (3 words)
        + [{"location": "37:2:1", "start": 1.60, "end": 1.85},
           {"location": "37:2:2", "start": 1.95, "end": 2.20},
           {"location": "37:2:3", "start": 2.30, "end": 2.40}]
        # verse 3 partial (2 words)
        + [{"location": "37:3:1", "start": 2.60, "end": 2.85},
           {"location": "37:3:2", "start": 2.95, "end": 3.50}]
    )
    monkeypatch.setattr(auto_split, "mfa_wait_result",
                        lambda *a, **k: [{"words": words}])
    out = auto_split.compute_auto_split("r", 37, "u1")
    assert out["kind"] == "cross_verse"
    assert out["source"] == "mfa"
    assert out["refs"] == ["37:1:1-37:1:7", "37:2:1-37:2:3", "37:3:1-37:3:2"]
    # midpoint(1.40,1.60)=1.50s → 1500 ms ; midpoint(2.40,2.60)=2.50s → 2500 ms
    assert out["cursors"] == [11_500, 12_500]


def test_cross_verse_3_verses_fallback_evencuts(monkeypatch):
    """MFA fails on 3-verse seg → 2 evenly-spaced cursors + 3 refs."""
    seg = {"segment_uid": "u1", "matched_ref": "37:1:1-37:3:2",
           "time_start": 10_000, "time_end": 16_000, "confidence": 0.9}
    _patch_seg(monkeypatch, seg)
    monkeypatch.setattr(auto_split, "get_word_counts",
                        lambda: {(37, 1): 7, (37, 2): 3, (37, 3): 5})
    monkeypatch.setattr(auto_split, "build_mfa_ref", lambda s: s["matched_ref"])

    def _boom(*_a, **_k):
        raise RuntimeError("MFA down")

    monkeypatch.setattr(auto_split, "mfa_upload_and_submit", _boom)
    out = auto_split.compute_auto_split("r", 37, "u1")
    assert out["kind"] == "cross_verse"
    assert out["source"] == "fallback"
    assert out["refs"] == ["37:1:1-37:1:7", "37:2:1-37:2:3", "37:3:1-37:3:2"]
    # N=3 → 2 evenly-spaced cursors at time_start + duration*(1/3), *(2/3)
    # = 10_000 + 2000 = 12_000 ; 10_000 + 4000 = 14_000.
    assert out["cursors"] == [12_000, 14_000]


def test_cross_verse_n_verses_word_count_mismatch(monkeypatch):
    """MFA returns wrong word total → fallback to even cuts."""
    seg = {"segment_uid": "u1", "matched_ref": "37:1:1-37:3:2",
           "time_start": 10_000, "time_end": 16_000, "confidence": 0.9}
    _patch_seg(monkeypatch, seg)
    monkeypatch.setattr(auto_split, "get_word_counts",
                        lambda: {(37, 1): 7, (37, 2): 3, (37, 3): 5})
    monkeypatch.setattr(auto_split, "build_mfa_ref", lambda s: s["matched_ref"])
    monkeypatch.setattr(auto_split, "mfa_upload_and_submit",
                        lambda *a, **k: ("evt", {}, "http://mfa"))
    # Only 5 words returned (expected 12) — len mismatch.
    monkeypatch.setattr(auto_split, "mfa_wait_result", lambda *a, **k: [{
        "words": [{"location": "37:1:1", "start": 0.0, "end": 0.1}] * 5,
    }])
    out = auto_split.compute_auto_split("r", 37, "u1")
    assert out["source"] == "fallback"
    assert out["cursors"] == [12_000, 14_000]


def test_single_verse_seg_returns_null(monkeypatch):
    seg = {"segment_uid": "u1", "matched_ref": "1:1:1-1:1:4",
           "time_start": 1000, "time_end": 5000, "confidence": 0.9}
    _patch_seg(monkeypatch, seg)
    out = auto_split.compute_auto_split("r", 1, "u1")
    assert out == {"cursors": None, "refs": None, "kind": None,
                   "source": "fallback"}


# ---------------------------------------------------------------------------
# compute_auto_split — repetition
# ---------------------------------------------------------------------------

def test_repetition_happy_path(monkeypatch):
    """Forward pass 1-3 then repeat 2-4 → 1 cursor, 2 refs."""
    seg = {
        "segment_uid": "u1", "matched_ref": "1:1:1-1:1:4",
        "time_start": 10_000, "time_end": 16_000, "confidence": 0.9,
        # wrap data: jumped TO word 2, jumped FROM word 3, repeated through word 4
        "wrap_word_ranges": [["1:1:2", "1:1:3", "1:1:4"]],
    }
    _patch_seg(monkeypatch, seg)
    monkeypatch.setattr(auto_split, "build_mfa_ref", lambda s: s["matched_ref"])
    monkeypatch.setattr(auto_split, "mfa_upload_and_submit",
                        lambda *a, **k: ("evt", {}, "http://mfa"))
    # Reading sequence: [1:1-1:3] (3 words) then [1:2-1:4] (3 words). MFA
    # returns words in reading order with duplicated locations.
    monkeypatch.setattr(auto_split, "mfa_wait_result", lambda *a, **k: [{
        "words": [
            {"location": "1:1:1", "start": 0.0, "end": 0.4},
            {"location": "1:1:2", "start": 0.5, "end": 0.9},
            {"location": "1:1:3", "start": 1.0, "end": 1.4},
            {"location": "1:1:2", "start": 1.6, "end": 2.0},
            {"location": "1:1:3", "start": 2.1, "end": 2.5},
            {"location": "1:1:4", "start": 2.6, "end": 3.0},
        ],
    }])
    out = auto_split.compute_auto_split("r", 1, "u1")
    # midpoint(1.4, 1.6) → seg-relative 1500 ms; absolute 11_500.
    assert out == {
        "cursors": [11_500],
        "refs": ["1:1:1-1:1:3", "1:1:2-1:1:4"],
        "kind": "repetition",
        "source": "mfa",
    }


def test_repetition_fallback_on_mfa_error(monkeypatch):
    """MFA dies → evenly-spaced cuts + suggested refs (no user-facing error)."""
    seg = {
        "segment_uid": "u1", "matched_ref": "1:1:1-1:1:4",
        "time_start": 10_000, "time_end": 16_000, "confidence": 0.9,
        "wrap_word_ranges": [["1:1:2", "1:1:3", "1:1:4"]],
    }
    _patch_seg(monkeypatch, seg)
    monkeypatch.setattr(auto_split, "build_mfa_ref", lambda s: s["matched_ref"])

    def _boom(*_a, **_k):
        raise RuntimeError("MFA down")

    monkeypatch.setattr(auto_split, "mfa_upload_and_submit", _boom)
    out = auto_split.compute_auto_split("r", 1, "u1")
    assert out["kind"] == "repetition"
    assert out["source"] == "fallback"
    # N=2 sections → 1 evenly-spaced cursor at seg midpoint.
    assert out["cursors"] == [13_000]
    assert out["refs"] == ["1:1:1-1:1:3", "1:1:2-1:1:4"]


def test_repetition_fallback_when_ffmpeg_fails(monkeypatch):
    seg = {
        "segment_uid": "u1", "matched_ref": "1:1:1-1:1:4",
        "time_start": 10_000, "time_end": 16_000, "confidence": 0.9,
        "wrap_word_ranges": [["1:1:2", "1:1:3", "1:1:4"]],
    }
    _patch_seg(monkeypatch, seg)
    monkeypatch.setattr(auto_split, "_slice_to_wav", lambda *_a, **_k: False)
    monkeypatch.setattr(auto_split, "build_mfa_ref", lambda s: s["matched_ref"])
    monkeypatch.setattr(auto_split, "mfa_upload_and_submit",
                        lambda *a, **k: pytest.fail("should not call MFA"))
    out = auto_split.compute_auto_split("r", 1, "u1")
    assert out["kind"] == "repetition"
    assert out["source"] == "fallback"
    assert out["cursors"] == [13_000]
