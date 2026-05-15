"""Tests for services.auto_split — unified compute_auto_split contract.

Stubs the MFA HTTP client and ffmpeg invocation so we exercise:
- cross-verse boundary + suggested two-ref output
- repetition reading-sequence boundary detection + N-way refs
- silent-fallback shape (even cuts, midpoint) on MFA/ffmpeg failure
without any network or binary dependency.
"""
from __future__ import annotations

import pytest

from services import audio_source, auto_split


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_boundary_ms_at_ayah_midpoint_between_words():
    words = [
        {"location": "37:151:1", "start": 0.10, "end": 0.40},
        {"location": "37:151:2", "start": 0.45, "end": 0.80},
        {"location": "37:152:1", "start": 0.90, "end": 1.20},
    ]
    # midpoint(0.80, 0.90) = 0.85 s → 850 ms
    assert auto_split._boundary_ms_at_ayah(words, 152) == 850


def test_boundary_ms_returns_none_when_boundary_missing():
    words = [
        {"location": "37:151:1", "start": 0.10, "end": 0.40},
    ]
    assert auto_split._boundary_ms_at_ayah(words, 152) is None


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


def test_suggest_cross_verse_refs_uses_word_counts():
    word_counts = {(37, 151): 39, (37, 152): 26}
    assert auto_split._suggest_cross_verse_refs("37:151:3-37:152:2", word_counts) == [
        "37:151:3-37:151:39", "37:152:1-37:152:2",
    ]


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
    seg = {"segment_uid": "u1", "matched_ref": "37:151:3-37:152:2",
           "time_start": 10_000, "time_end": 14_000, "confidence": 0.9}
    _patch_seg(monkeypatch, seg)
    monkeypatch.setattr(auto_split, "build_mfa_ref", lambda s: s["matched_ref"])
    monkeypatch.setattr(auto_split, "mfa_upload_and_submit",
                        lambda *a, **k: ("evt", {}, "http://mfa"))
    monkeypatch.setattr(auto_split, "mfa_wait_result", lambda *a, **k: [{
        "words": [
            {"location": "37:151:3", "start": 0.10, "end": 1.40},
            {"location": "37:152:1", "start": 1.60, "end": 2.40},
        ],
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
    assert out["cursors"] == [12_000]  # midpoint
    assert out["refs"] == ["37:151:3-37:151:39", "37:152:1-37:152:2"]


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
