"""``sample--<id>`` slugs route every per-reciter path under ``samples/<id>/``."""

from __future__ import annotations

import pytest

from services.storage import storage_paths as sp


def test_sample_slug_roundtrip():
    slug = sp.sample_slug("abc")
    assert slug == "sample--abc"
    assert sp.is_sample_slug(slug) and not sp.is_sample_slug("abc")
    assert sp.sample_id_from_slug(slug) == "abc"
    with pytest.raises(ValueError):
        sp.sample_id_from_slug("abc")


def test_sample_paths_branch_under_samples_prefix():
    assert sp.reciter_dir("sample--x") == "samples/x"
    assert sp.detailed_path("sample--x") == "samples/x/detailed.json"
    assert sp.prefetched_audio_path("sample--x", 2) == "samples/x/audio/2.mp3"
    assert sp.prefetched_peaks_path("sample--x", 2) == "samples/x/peaks/2.json.gz"
    assert sp.audio_manifest_path("sample--x") == "samples/x/audio_manifest.json"
    assert sp.sample_source_path("x") == "samples/x/source.json"
    assert sp.sample_sidecar_path("x") == "samples/x/sample.json"


def test_real_slugs_unchanged():
    assert sp.reciter_dir("husary") == "reciters/husary"
    assert sp.detailed_path("husary") == "reciters/husary/detailed.json"
    assert sp.audio_manifest_path("husary") == "catalog/audio_manifest/husary.json"
