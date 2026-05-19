"""Tests for ``services.audio_meta`` — sidecar-backed VBR lookups.

The sidecar lives at ``catalog/audio_manifest/<slug>.json`` and the per-chapter
entry carries ``bitrate_mode`` ("vbr" | "cbr"), plus the URL used for the
reverse-lookup that powers the audio-proxy short-circuit.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def stage(monkeypatch):
    """Yield a helper that stages a sidecar dict in the audio_manifest
    cache so the bucket read is bypassed entirely. Each test stages its
    own payload.
    """
    from services.audio import audio_meta as audio_meta_mod

    audio_meta_mod._clear_for_test()

    def _set(slug: str, chapters: dict) -> None:
        audio_meta_mod._stage_for_test(slug, {"chapters": chapters})

    yield _set

    audio_meta_mod._clear_for_test()


def test_vbr_chapters_for_reciter_returns_sorted_chapter_numbers(stage):
    from services.audio_meta import vbr_chapters_for_reciter

    stage("alghazali", {
        "76": {"url": "u76", "bitrate_mode": "vbr"},
        "1": {"url": "u1", "bitrate_mode": "vbr"},
        "100": {"url": "u100", "bitrate_mode": "vbr"},
    })
    assert vbr_chapters_for_reciter("alghazali") == [1, 76, 100]


def test_vbr_chapters_for_reciter_skips_non_vbr_entries(stage):
    from services.audio_meta import vbr_chapters_for_reciter

    stage("alghazali", {
        "1": {"url": "u1", "bitrate_mode": "vbr"},
        "2": {"url": "u2", "bitrate_mode": "cbr"},
        "3": {"url": "u3"},
    })
    assert vbr_chapters_for_reciter("alghazali") == [1]


def test_vbr_chapters_for_reciter_unknown_reciter_returns_empty(stage):
    from services.audio_meta import vbr_chapters_for_reciter

    stage("alghazali", {"1": {"url": "u1", "bitrate_mode": "vbr"}})
    assert vbr_chapters_for_reciter("nonexistent_reciter") == []


def test_vbr_chapters_for_reciter_missing_sidecar_returns_empty():
    from services.audio_meta import vbr_chapters_for_reciter

    # No fixture → empty cache, sidecar read returns None via the bucket
    # backend's NotFound — function degrades to an empty list.
    assert vbr_chapters_for_reciter("never-staged") == []


def test_is_vbr_and_is_vbr_for_url(stage):
    from services.audio_meta import is_vbr, is_vbr_for_url

    stage("rec", {
        "1": {"url": "https://cdn/1.mp3", "bitrate_mode": "vbr"},
        "2": {"url": "https://cdn/2.mp3", "bitrate_mode": "cbr"},
    })
    assert is_vbr("rec", 1) is True
    assert is_vbr("rec", 2) is False
    assert is_vbr("rec", 99) is False
    assert is_vbr_for_url("rec", "https://cdn/1.mp3") is True
    assert is_vbr_for_url("rec", "https://cdn/2.mp3") is False
    assert is_vbr_for_url("rec", "https://cdn/unknown.mp3") is False


def test_chapter_for_url_and_chapter_urls(stage):
    from services.audio_meta import chapter_for_url, chapter_urls

    stage("rec", {
        "1": {"url": "https://cdn/1.mp3", "bitrate_mode": "cbr"},
        "5:3": {"url": "https://cdn/5_3.mp3"},
    })
    assert chapter_for_url("rec", "https://cdn/1.mp3") == "1"
    assert chapter_for_url("rec", "https://cdn/5_3.mp3") == "5:3"
    assert chapter_for_url("rec", "missing") is None
    assert chapter_urls("rec") == {
        "1": "https://cdn/1.mp3",
        "5:3": "https://cdn/5_3.mp3",
    }
