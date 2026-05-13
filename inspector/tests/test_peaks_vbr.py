"""Branch selection in ``compute_segment_peaks``.

When the resolver returns local bytes (bucket prefetch or disk cache), the
segment decode goes through ``_ffmpeg_decode_segment`` (frame-accurate, works
for VBR + CBR). When the resolver has only the CDN URL, decode falls back to
the byte-arithmetic HTTP Range path — CBR-correct, VBR-approximate, but the
only option in the stripped inspector image (ffmpeg ``--disable-network``).
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


def test_local_bytes_route_through_ffmpeg_decode(tmp_path, monkeypatch):
    from services import audio_source, peaks

    decode_calls: list = []
    range_calls: list = []

    monkeypatch.setattr(peaks, "peaks_cache_path", lambda reciter, key: tmp_path / "p.json")
    monkeypatch.setattr(audio_source, "resolve", lambda r, u: _fake_source(has_local=True))
    monkeypatch.setattr(peaks, "_ffmpeg_decode_segment",
                        lambda src, s, d: decode_calls.append((src, s, d)) or _pcm())
    monkeypatch.setattr(peaks, "_range_decode_segment",
                        lambda *a, **kw: range_calls.append(a) or None)

    data = peaks.compute_segment_peaks("https://cdn.example/audio.mp3", 1000, 2000, "r", chapter=7)
    assert data is not None
    assert len(decode_calls) == 1
    assert range_calls == []
    src, start, dur = decode_calls[0]
    assert src.has_local_bytes is True
    assert start == 1.0
    assert dur == 1.0


def test_no_local_bytes_falls_back_to_range_decode(tmp_path, monkeypatch):
    from services import audio_source, peaks

    decode_calls: list = []
    range_calls: list = []

    monkeypatch.setattr(peaks, "peaks_cache_path", lambda reciter, key: tmp_path / "p.json")
    monkeypatch.setattr(audio_source, "resolve", lambda r, u: _fake_source(has_local=False))
    monkeypatch.setattr(peaks, "_get_audio_meta", lambda url: {"id3_offset": 0, "bytes_per_sec": 16_000})
    monkeypatch.setattr(peaks, "_ffmpeg_decode_segment",
                        lambda *a, **kw: decode_calls.append(a) or None)
    monkeypatch.setattr(peaks, "_range_decode_segment",
                        lambda *a, **kw: range_calls.append(a) or _pcm())

    data = peaks.compute_segment_peaks("https://cdn.example/audio.mp3", 1000, 2000, "r", chapter=7)
    assert data is not None
    assert decode_calls == []
    assert len(range_calls) == 1
