"""Dependency-free waveform-peak computation + v3 slim packing for the HF Job.

Mirror of ``inspector/services/audio/peaks.py::compute_audio_peaks`` and
``inspector/services/audio/peaks_slim.py::pack_slim`` but with NO ``config``
import, so it is stageable into the timestamps job (which ships only
``scripts/``, not ``inspector/services`` + its Flask config). Output blobs are
byte-identical to ``peaks_slim.pack_slim`` — guarded by
``qua_shared/tests/test_peaks_compute.py::test_pack_parity`` so the two never
drift.

Constants inlined from ``inspector/config.py`` + ``peaks_slim.py`` — keep in
lockstep: ``PEAKS_FFMPEG_SAMPLE_RATE`` (8000), ``PEAKS_BUCKETS_PER_SEC`` (30),
``MIN_FULL_PEAK_BUCKETS`` (100), ``PEAKS_PCM_NORMALIZER`` (32768),
``PEAKS_SLIM_BPS`` (10), ``SLIM_SCHEMA_VERSION`` (3).
"""

from __future__ import annotations

import base64
import gzip
import json
import struct
import subprocess

import numpy as np

# Inlined from inspector/config.py (HD overview peaks contract).
PEAKS_FFMPEG_SAMPLE_RATE = 8000
PEAKS_BUCKETS_PER_SEC = 30
MIN_FULL_PEAK_BUCKETS = 100
PEAKS_PCM_NORMALIZER = 32768.0
PEAKS_HD_SCHEMA_VERSION = 2  # HD float shape pack consumes (re-stamped to v3)
_FFMPEG_TIMEOUT = 600

# Inlined from inspector/services/audio/peaks_slim.py (frozen v3 wire format).
PEAKS_SLIM_BPS = 10
SLIM_SCHEMA_VERSION = 3
_INT8_SCALE = 127


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


def _decimate(peaks: np.ndarray, src_bps: int, dst_bps: int) -> np.ndarray:
    """min-of-mins / max-of-maxes over windows. Mirror of peaks_slim._decimate."""
    if dst_bps >= src_bps:
        return peaks
    factor = src_bps // dst_bps
    n_full = (len(peaks) // factor) * factor
    if n_full == 0:
        return peaks[:0]
    trimmed = peaks[:n_full].reshape(-1, factor, 2)
    mn = trimmed[:, :, 0].min(axis=1)
    mx = trimmed[:, :, 1].max(axis=1)
    tail = peaks[n_full:]
    if len(tail):
        mn = np.concatenate([mn, [tail[:, 0].min()]])
        mx = np.concatenate([mx, [tail[:, 1].max()]])
    return np.stack([mn, mx], axis=1)


def pack_slim(hd_doc: dict, target_bps: int = PEAKS_SLIM_BPS) -> bytes:
    """Pack an HD ``compute_audio_peaks`` output into the canonical gzip blob.

    Byte-identical to ``inspector/services/audio/peaks_slim.py::pack_slim``
    (parity-tested). Output goes to ``reciters/<slug>/peaks/<ch>.json.gz``.
    """
    if not isinstance(hd_doc, dict) or "peaks" not in hd_doc or "duration_ms" not in hd_doc:
        raise ValueError("pack_slim: expected dict with 'peaks' and 'duration_ms'")
    arr = np.asarray(hd_doc["peaks"], dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError(f"pack_slim: expected peaks shape (N, 2), got {arr.shape}")
    arr = _decimate(arr, src_bps=30, dst_bps=target_bps)
    i8 = np.clip(np.round(arr * _INT8_SCALE), -_INT8_SCALE, _INT8_SCALE).astype(np.int8)
    doc = {
        "schema_version": SLIM_SCHEMA_VERSION,
        "duration_ms": int(hd_doc["duration_ms"]),
        "q": "int8",
        "bps": target_bps,
        "n": int(i8.shape[0]),
        "peaks_b64": base64.b64encode(i8.tobytes()).decode("ascii"),
    }
    return gzip.compress(
        json.dumps(doc, separators=(",", ":")).encode("utf-8"),
        compresslevel=6, mtime=0,
    )
