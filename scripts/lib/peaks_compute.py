"""Dependency-free waveform-peak computation for the HF Job.

Mirror of ``inspector/services/audio/peaks.py::compute_audio_peaks`` but with
NO ``config`` import, so it is stageable into the timestamps job (which only
ships ``scripts/``, not ``inspector/services`` + its Flask config). The output
shape is byte-compatible with what ``peaks_slim.pack_slim`` expects
(``{schema_version, duration_ms, peaks: [[mn, mx], ...]}`` at 30 bps).

Constants are inlined from ``inspector/config.py`` defaults — keep in lockstep:
``PEAKS_FFMPEG_SAMPLE_RATE`` (8000), ``PEAKS_BUCKETS_PER_SEC`` (30),
``MIN_FULL_PEAK_BUCKETS`` (100), ``PEAKS_PCM_NORMALIZER`` (32768).
"""

from __future__ import annotations

import struct
import subprocess

# Inlined from inspector/config.py (HD overview peaks contract).
PEAKS_FFMPEG_SAMPLE_RATE = 8000
PEAKS_BUCKETS_PER_SEC = 30
MIN_FULL_PEAK_BUCKETS = 100
PEAKS_PCM_NORMALIZER = 32768.0
PEAKS_HD_SCHEMA_VERSION = 2  # HD float shape pack_slim consumes (it re-stamps v3)
_FFMPEG_TIMEOUT = 600


def _bucket_pcm_minmax(samples, num_samples: int, num_buckets: int) -> list[list[float]]:
    """Bucket a PCM signal into ``num_buckets`` min/max pairs over ``[0, n)``.

    Float stride so buckets exactly tile the range (no dropped tail) — mirrors
    ``peaks.py::_bucket_pcm_minmax`` exactly so the offline + job peaks match.
    """
    if num_samples <= 0 or num_buckets <= 0:
        return []
    stride = num_samples / num_buckets
    out: list[list[float]] = []
    for i in range(num_buckets):
        start = int(round(i * stride))
        end = int(round((i + 1) * stride))
        if start >= num_samples:
            break
        if end <= start:
            continue
        end = min(end, num_samples)
        block = samples[start:end]
        if not block:
            continue
        mn = min(block) / PEAKS_PCM_NORMALIZER
        mx = max(block) / PEAKS_PCM_NORMALIZER
        out.append([round(mn, 4), round(mx, 4)])
    return out


def compute_audio_peaks(audio_source: str) -> dict | None:
    """Compute HD waveform peaks for a local file path or URL.

    Returns ``{schema_version, duration_ms, peaks}`` (the shape ``pack_slim``
    consumes) or ``None`` on any ffmpeg/decode failure.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", audio_source, "-f", "s16le", "-ac", "1",
             "-ar", str(PEAKS_FFMPEG_SAMPLE_RATE), "-v", "quiet", "-"],
            capture_output=True, timeout=_FFMPEG_TIMEOUT,
        )
        if result.returncode != 0 or len(result.stdout) < 4:
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    raw = result.stdout
    num_samples = len(raw) // 2
    if num_samples == 0:
        return None
    samples = struct.unpack(f"<{num_samples}h", raw)

    duration_ms = int(num_samples / PEAKS_FFMPEG_SAMPLE_RATE * 1000)
    duration_sec = num_samples / PEAKS_FFMPEG_SAMPLE_RATE
    num_buckets = max(MIN_FULL_PEAK_BUCKETS, int(duration_sec * PEAKS_BUCKETS_PER_SEC))
    peaks = _bucket_pcm_minmax(samples, num_samples, num_buckets)

    return {"schema_version": PEAKS_HD_SCHEMA_VERSION,
            "duration_ms": duration_ms, "peaks": peaks}
