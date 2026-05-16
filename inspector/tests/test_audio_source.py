"""Priority + sidecar-readthrough tests for ``services.audio_source.resolve``.

The resolver is the single chokepoint for "where do this chapter's audio
bytes live right now". Confirms the priority chain (bucket bytes → disk
path → CDN URL) and that ``vbr`` / ``bitrate_kbps`` / ``chapter_key`` flow
through from the per-slug sidecar.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def stub_env(monkeypatch, tmp_path):
    """Wire ``audio_source`` to stub backends so each test can vary the
    three signals (bucket bytes, disk file, sidecar entry) independently.
    """
    from services import audio_fetch, audio_meta, audio_source, cache

    audio_meta._SIDECAR_CACHE.clear()

    state: dict = {"bucket": None, "disk_dir": tmp_path}

    monkeypatch.setattr(
        audio_fetch, "read_prefetched_audio_bytes",
        lambda *_a, **_k: state["bucket"],
    )

    def _disk_path(reciter: str, url: str):
        # Mirror real cache.audio_cache_path layout but rooted in tmp_path so
        # the test can drop a real file when it wants the disk-hit branch.
        return tmp_path / reciter / "audio" / f"{abs(hash(url))}.mp3"

    monkeypatch.setattr(cache, "audio_cache_path", _disk_path)

    yield state, audio_source, audio_meta


def test_bucket_bytes_win(stub_env):
    state, audio_source, audio_meta = stub_env
    audio_meta._SIDECAR_CACHE["rec"] = {
        "chapters": {"1": {"url": "https://cdn/1.mp3", "bitrate_mode": "vbr",
                            "bitrate_kbps": 96}},
    }
    state["bucket"] = b"PREFETCHED"

    src = audio_source.resolve("rec", "https://cdn/1.mp3")
    assert src.data == b"PREFETCHED"
    assert src.path is None
    assert src.has_local_bytes is True
    assert src.vbr is True
    assert src.bitrate_kbps == 96
    assert src.chapter_key == "1"


def test_disk_used_when_no_bucket(stub_env, tmp_path):
    state, audio_source, audio_meta = stub_env
    audio_meta._SIDECAR_CACHE["rec"] = {
        "chapters": {"1": {"url": "https://cdn/1.mp3", "bitrate_mode": "cbr"}},
    }
    # Stage a disk file at the path the patched cache.audio_cache_path returns.
    from services import cache
    p = cache.audio_cache_path("rec", "https://cdn/1.mp3")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"ondisk")

    src = audio_source.resolve("rec", "https://cdn/1.mp3")
    assert src.data is None
    assert src.path == p
    assert src.has_local_bytes is True
    assert src.vbr is False


def test_cdn_only_when_nothing_local(stub_env):
    state, audio_source, audio_meta = stub_env
    audio_meta._SIDECAR_CACHE["rec"] = {
        "chapters": {"1": {"url": "https://cdn/1.mp3", "bitrate_mode": "cbr"}},
    }

    src = audio_source.resolve("rec", "https://cdn/1.mp3")
    assert src.data is None
    assert src.path is None
    assert src.has_local_bytes is False
    assert src.cdn_url == "https://cdn/1.mp3"


def test_unknown_url_yields_blank_metadata(stub_env):
    _, audio_source, audio_meta = stub_env
    audio_meta._SIDECAR_CACHE["rec"] = {"chapters": {}}

    src = audio_source.resolve("rec", "https://cdn/unknown.mp3")
    assert src.vbr is False
    assert src.bitrate_kbps is None
    assert src.chapter_key is None
