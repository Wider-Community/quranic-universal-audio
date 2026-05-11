"""VBR-safe branch selection for segment peak extraction."""
from __future__ import annotations

import struct


def _pcm(samples: int = 80) -> bytes:
    return struct.pack(f"<{samples}h", *([1000] * samples))


def test_segment_peaks_uses_chapter_vbr_before_url_lookup(tmp_path, monkeypatch):
    from services import peaks

    calls: list[tuple[str, float, float]] = []

    monkeypatch.setattr(peaks, "peaks_cache_path", lambda reciter, key: tmp_path / "peaks.json")
    monkeypatch.setattr(peaks.cache, "audio_cache_path", lambda reciter, url: tmp_path / "missing.mp3")
    monkeypatch.setattr(peaks, "is_vbr", lambda reciter, chapter: reciter == "r" and str(chapter) == "7")
    monkeypatch.setattr(peaks, "is_vbr_for_url", lambda reciter, url: False)
    monkeypatch.setattr(peaks, "_ffmpeg_decode_segment", lambda source, start, duration: calls.append((source, start, duration)) or _pcm())
    monkeypatch.setattr(peaks, "_range_decode_segment", lambda *args, **kwargs: None)

    data = peaks.compute_segment_peaks(
        "https://cdn.example/audio.mp3",
        1000,
        2000,
        "r",
        chapter=7,
    )

    assert data is not None
    assert data["start_ms"] == 1000
    assert calls == [("https://cdn.example/audio.mp3", 1.0, 1.0)]
