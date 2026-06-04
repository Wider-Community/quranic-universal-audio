"""Priority + sidecar-readthrough tests for ``services.audio_source.resolve``.

The resolver is the single chokepoint for "where do this chapter's audio
bytes live right now". Confirms the priority chain (bucket bytes → CDN URL)
and that ``vbr`` / ``bitrate_kbps`` / ``chapter_key`` flow through from the
per-slug sidecar.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def stub_env(monkeypatch):
    """Wire ``audio_source`` to stub backends so each test can vary the
    two signals (bucket bytes, sidecar entry) independently.
    """
    from services import audio_fetch, audio_meta, audio_source

    audio_meta._clear_for_test()

    state: dict = {"bucket": None, "local_path": None}

    monkeypatch.setattr(
        audio_fetch, "read_prefetched_audio_bytes",
        lambda *_a, **_k: state["bucket"],
    )
    monkeypatch.setattr(
        audio_fetch, "read_prefetched_audio_local_path",
        lambda *_a, **_k: state["local_path"],
    )

    yield state, audio_source, audio_meta


def test_bucket_local_path_wins(stub_env, tmp_path):
    state, audio_source, audio_meta = stub_env
    audio_meta._stage_for_test("rec", {
        "chapters": {"1": {"url": "https://cdn/1.mp3", "bitrate_mode": "cbr"}},
    })
    p = tmp_path / "1.mp3"
    p.write_bytes(b"x")
    state["local_path"] = p

    src = audio_source.resolve("rec", "https://cdn/1.mp3")
    assert src.path == p
    assert src.data is None
    assert src.has_local_bytes is True


def test_bucket_bytes_win(stub_env):
    state, audio_source, audio_meta = stub_env
    audio_meta._stage_for_test("rec", {
        "chapters": {"1": {"url": "https://cdn/1.mp3", "bitrate_mode": "vbr",
                            "bitrate_kbps": 96}},
    })
    state["bucket"] = b"PREFETCHED"

    src = audio_source.resolve("rec", "https://cdn/1.mp3")
    assert src.data == b"PREFETCHED"
    assert src.path is None
    assert src.has_local_bytes is True
    assert src.vbr is True
    assert src.bitrate_kbps == 96
    assert src.chapter_key == "1"


def test_cdn_only_when_nothing_local(stub_env):
    state, audio_source, audio_meta = stub_env
    audio_meta._stage_for_test("rec", {
        "chapters": {"1": {"url": "https://cdn/1.mp3", "bitrate_mode": "cbr"}},
    })

    src = audio_source.resolve("rec", "https://cdn/1.mp3")
    assert src.data is None
    assert src.path is None
    assert src.has_local_bytes is False
    assert src.cdn_url == "https://cdn/1.mp3"


def test_unknown_url_yields_blank_metadata(stub_env):
    _, audio_source, audio_meta = stub_env
    audio_meta._stage_for_test("rec", {"chapters": {}})

    src = audio_source.resolve("rec", "https://cdn/unknown.mp3")
    assert src.vbr is False
    assert src.bitrate_kbps is None
    assert src.chapter_key is None


# ---------------------------------------------------------------------------
# read_prefetched_peaks_duration_ms — slim-header fallback length source
# ---------------------------------------------------------------------------


def _packed_envelope(duration_ms: int) -> bytes:
    """A minimal valid slim peaks blob carrying ``duration_ms`` in its header."""
    from services.audio.peaks_slim import pack_slim

    return pack_slim({"schema_version": 2, "duration_ms": duration_ms,
                      "peaks": [[-0.5, 0.5]] * 30})


def test_peaks_duration_ms_reads_header(monkeypatch):
    from services import audio_fetch, audio_meta
    from services.audio import audio_fetch as af_mod

    audio_meta._clear_for_test()
    audio_meta._stage_for_test("rec", {
        "chapters": {"1": {"url": "https://cdn/1.mp3"}},
    })
    backend = type("B", (), {"read_bytes": staticmethod(
        lambda path: _packed_envelope(47000))})()
    monkeypatch.setattr(af_mod, "get_backend", lambda: backend)

    assert audio_fetch.read_prefetched_peaks_duration_ms("rec", "https://cdn/1.mp3") == 47000
    audio_meta._clear_for_test()


def test_peaks_duration_ms_none_when_peaks_absent(monkeypatch):
    from services import audio_fetch, audio_meta
    from services.audio import audio_fetch as af_mod

    audio_meta._clear_for_test()
    audio_meta._stage_for_test("rec", {
        "chapters": {"1": {"url": "https://cdn/1.mp3"}},
    })

    def _missing(path):
        raise FileNotFoundError(path)

    backend = type("B", (), {"read_bytes": staticmethod(_missing)})()
    monkeypatch.setattr(af_mod, "get_backend", lambda: backend)

    assert audio_fetch.read_prefetched_peaks_duration_ms("rec", "https://cdn/1.mp3") is None
    # Unknown URL → None without touching the backend.
    assert audio_fetch.read_prefetched_peaks_duration_ms("rec", "https://cdn/zzz.mp3") is None
    audio_meta._clear_for_test()
