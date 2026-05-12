"""Tests for services.auto_split — verse-boundary computation + MFA fallback.

Stubs the MFA HTTP client and ffmpeg invocation so we can exercise the
boundary-midpoint math + the silent-fallback contract without any network or
binary dependency.
"""
from __future__ import annotations

import pytest

from services import auto_split


def test_boundary_ms_midpoint_between_words():
    """Boundary ms is the rounded midpoint between prev.end and curr.start."""
    words = [
        {"location": "37:151:1", "start": 0.10, "end": 0.40},
        {"location": "37:151:2", "start": 0.45, "end": 0.80},
        {"location": "37:152:1", "start": 0.90, "end": 1.20},
        {"location": "37:152:2", "start": 1.25, "end": 1.60},
    ]
    # midpoint(0.80, 0.90) = 0.85 s → 850 ms
    assert auto_split._boundary_ms_from_words(words, 152) == 850


def test_boundary_ms_returns_none_when_boundary_first():
    """No usable boundary when the very first word already belongs to verse B."""
    words = [
        {"location": "37:152:1", "start": 0.10, "end": 0.40},
    ]
    assert auto_split._boundary_ms_from_words(words, 152) is None


def test_boundary_ms_returns_none_when_boundary_missing():
    """No usable boundary when verse B never appears in MFA output."""
    words = [
        {"location": "37:151:1", "start": 0.10, "end": 0.40},
        {"location": "37:151:2", "start": 0.45, "end": 0.80},
    ]
    assert auto_split._boundary_ms_from_words(words, 152) is None


def test_is_cross_verse():
    assert auto_split._is_cross_verse("37:151:3-37:152:2")
    assert not auto_split._is_cross_verse("1:1:1-1:1:4")
    assert not auto_split._is_cross_verse("garbage")


def test_compute_auto_split_ms_returns_none_for_single_verse(monkeypatch):
    """Single-verse seg short-circuits before any MFA call."""
    seg = {
        "segment_uid": "u1", "matched_ref": "1:1:1-1:1:4",
        "time_start": 1000, "time_end": 5000, "confidence": 0.9,
    }
    monkeypatch.setattr(auto_split, "_find_segment",
                        lambda *_a, **_k: {**seg, "_audio_url": "http://a"})
    # Will raise if the MFA path is reached.
    monkeypatch.setattr(auto_split, "mfa_upload_and_submit",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("MFA called")))
    assert auto_split.compute_auto_split_ms("r", 1, "u1") is None


def test_compute_auto_split_ms_happy_path(monkeypatch, tmp_path):
    seg = {
        "segment_uid": "u1", "matched_ref": "37:151:3-37:152:2",
        "time_start": 10_000, "time_end": 14_000, "confidence": 0.9,
    }
    monkeypatch.setattr(auto_split, "_find_segment",
                        lambda *_a, **_k: {**seg, "_audio_url": "http://a"})
    monkeypatch.setattr(auto_split, "_slice_to_wav",
                        lambda *_a, **_k: True)
    monkeypatch.setattr(auto_split, "mfa_upload_and_submit",
                        lambda *a, **k: ("evt", {}, "http://mfa"))
    monkeypatch.setattr(auto_split, "mfa_wait_result", lambda *a, **k: [{
        "words": [
            {"location": "37:151:3", "start": 0.10, "end": 1.40},
            {"location": "37:152:1", "start": 1.60, "end": 2.40},
            {"location": "37:152:2", "start": 2.50, "end": 3.20},
        ],
    }])
    # Midpoint(1.40, 1.60) = 1.50 s = 1500 ms (seg-relative) + 10_000 = 11_500.
    assert auto_split.compute_auto_split_ms("r", 37, "u1") == 11_500


def test_compute_auto_split_ms_falls_back_on_mfa_error(monkeypatch):
    seg = {
        "segment_uid": "u1", "matched_ref": "37:151:3-37:152:2",
        "time_start": 10_000, "time_end": 14_000, "confidence": 0.9,
    }
    monkeypatch.setattr(auto_split, "_find_segment",
                        lambda *_a, **_k: {**seg, "_audio_url": "http://a"})
    monkeypatch.setattr(auto_split, "_slice_to_wav",
                        lambda *_a, **_k: True)

    def _boom(*_a, **_k):
        raise RuntimeError("MFA Space 500")

    monkeypatch.setattr(auto_split, "mfa_upload_and_submit", _boom)
    assert auto_split.compute_auto_split_ms("r", 37, "u1") is None


def test_compute_auto_split_ms_falls_back_when_ffmpeg_fails(monkeypatch):
    seg = {
        "segment_uid": "u1", "matched_ref": "37:151:3-37:152:2",
        "time_start": 10_000, "time_end": 14_000, "confidence": 0.9,
    }
    monkeypatch.setattr(auto_split, "_find_segment",
                        lambda *_a, **_k: {**seg, "_audio_url": "http://a"})
    monkeypatch.setattr(auto_split, "_slice_to_wav",
                        lambda *_a, **_k: False)
    monkeypatch.setattr(auto_split, "mfa_upload_and_submit",
                        lambda *a, **k: pytest.fail("should not call MFA"))
    assert auto_split.compute_auto_split_ms("r", 37, "u1") is None
