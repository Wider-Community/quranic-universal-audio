"""Readiness probe — which by-surah chapters lack bucket audio / peaks.

A non-blocking warn signal for the Releases tab. The timestamps job no longer
writes audio or peaks (both land offline), so this reports what's still
missing. Uses the filesystem backend + a staged audio manifest sidecar.
"""

from __future__ import annotations

import pytest

from services.admin import release_readiness
from services.audio import audio_meta
from services.storage import cache


@pytest.fixture(autouse=True)
def _clear_readiness_cache():
    """Readiness is TTL-cached by slug — reset between tests for isolation."""
    cache._readiness.clear()
    yield
    cache._readiness.clear()


def _stage_manifest(slug: str, n_chapters: int) -> None:
    chapters = {str(i): {"url": f"https://cdn/{slug}/{i}.mp3"} for i in range(1, n_chapters + 1)}
    audio_meta._stage_for_test(slug, {"chapters": chapters})


def _write(backend, rel: str) -> None:
    backend.write_bytes_atomic(rel, b"x")


def test_none_when_manifest_has_no_by_surah_chapters(tmp_reciter_dir):
    audio_meta._stage_for_test("by_ayah_only", {"chapters": {"2:255": {"url": "u"}}})
    assert release_readiness.reciter_bucket_readiness("by_ayah_only") is None


def test_all_present_reports_zero_missing(tmp_reciter_dir):
    from services import hf_bucket

    slug = "complete_reciter"
    _stage_manifest(slug, 3)
    backend = hf_bucket.get_backend()
    for i in (1, 2, 3):
        _write(backend, f"reciters/{slug}/audio/{i}.mp3")
        _write(backend, f"reciters/{slug}/peaks/{i}.json.gz")
    out = release_readiness.reciter_bucket_readiness(slug)
    assert out == {
        "audio_missing": 0,
        "peaks_missing": 0,
        "audio_missing_chapters": [],
        "peaks_missing_chapters": [],
    }


def test_missing_audio_and_peaks_listed_sorted(tmp_reciter_dir):
    from services import hf_bucket

    slug = "partial_reciter"
    _stage_manifest(slug, 3)
    backend = hf_bucket.get_backend()
    # Chapter 2 has audio but no peaks; chapter 3 has neither; chapter 1 has both.
    _write(backend, f"reciters/{slug}/audio/1.mp3")
    _write(backend, f"reciters/{slug}/peaks/1.json.gz")
    _write(backend, f"reciters/{slug}/audio/2.mp3")
    out = release_readiness.reciter_bucket_readiness(slug)
    assert out["audio_missing_chapters"] == [3]
    assert out["peaks_missing_chapters"] == [2, 3]
    assert out["audio_missing"] == 1
    assert out["peaks_missing"] == 2


def test_missing_dirs_count_everything_missing(tmp_reciter_dir):
    slug = "fresh_reciter"
    _stage_manifest(slug, 2)
    # No audio/ or peaks/ dirs written at all → StorageNotFound → all missing.
    out = release_readiness.reciter_bucket_readiness(slug)
    assert out["audio_missing"] == 2
    assert out["peaks_missing"] == 2
