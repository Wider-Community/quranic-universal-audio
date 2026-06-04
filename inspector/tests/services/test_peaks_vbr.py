"""Decode-source selection in ``compute_segment_peaks``.

``_ffmpeg_decode_segment`` is the single decode path: prefers ``src.path``,
then ``src.data``, then falls back to the URL (ffmpeg fetches HTTPS via the
network-enabled image build).
"""

from __future__ import annotations

import struct


def _pcm(samples: int = 80) -> bytes:
    return struct.pack(f"<{samples}h", *([1000] * samples))


def _fake_source(*, has_local: bool):
    from services import audio_source

    return audio_source.AudioSource(
        cdn_url="https://cdn.example/audio.mp3",
        data=b"\x00\x00" if has_local else None,
        path=None,
        vbr=False,
        bitrate_kbps=None,
        chapter_key="7",
    )


def test_local_bytes_route_through_ffmpeg_decode(monkeypatch):
    from services import audio_source, peaks

    decode_calls: list = []

    monkeypatch.setattr(audio_source, "resolve", lambda r, u: _fake_source(has_local=True))
    monkeypatch.setattr(
        peaks,
        "_ffmpeg_decode_segment",
        lambda src, url, s, d: decode_calls.append((src, url, s, d)) or _pcm(),
    )

    data = peaks.compute_segment_peaks("https://cdn.example/audio.mp3", 1000, 2000, "r", chapter=7)
    assert data is not None
    assert len(decode_calls) == 1
    src, url, start, dur = decode_calls[0]
    assert src.has_local_bytes is True
    assert url == "https://cdn.example/audio.mp3"
    assert start == 1.0
    assert dur == 1.0


def test_no_local_bytes_falls_back_to_url(monkeypatch):
    from services import audio_source, peaks

    decode_calls: list = []

    monkeypatch.setattr(audio_source, "resolve", lambda r, u: _fake_source(has_local=False))
    monkeypatch.setattr(
        peaks,
        "_ffmpeg_decode_segment",
        lambda src, url, s, d: decode_calls.append((src, url, s, d)) or _pcm(),
    )

    data = peaks.compute_segment_peaks("https://cdn.example/audio.mp3", 1000, 2000, "r", chapter=7)
    assert data is not None
    assert len(decode_calls) == 1
    src, url, start, dur = decode_calls[0]
    assert src.has_local_bytes is False
    assert url == "https://cdn.example/audio.mp3"
