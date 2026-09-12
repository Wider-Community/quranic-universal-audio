"""Chapter waveform peaks — HD compute via ffmpeg and the slim packed blob.

Lives in ``qua_shared`` so the acquire HF Job can bake ``peaks/<ch>.json.gz``
next to the audio it persists, with the exact bytes the Inspector runtime
would produce. ``inspector/services/audio/{peaks,peaks_slim}.py`` re-export
these for the app's own callers.

Shapes:

- HD doc (``compute_audio_peaks``): ``{schema_version, duration_ms, peaks}``
  with ``peaks`` a list of ``[min, max]`` floats in ``[-1, 1]`` at
  ``PEAKS_BUCKETS_PER_SEC`` density.
- Slim blob (``pack_slim``): one gzip member holding
  ``{schema_version, duration_ms, q: "int8", bps, n, peaks_b64}`` — the bytes
  stored at ``reciters/<slug>/peaks/<chapter>.json.gz``.
"""

from __future__ import annotations

import base64
import gzip
import json
import struct
import subprocess

import numpy as np

#: HD density used by ``compute_audio_peaks`` (buckets per second).
PEAKS_BUCKETS_PER_SEC = 30
#: Slim density stored on the bucket. Decided by the resolution benchmark in
#: ``docs/peaks_density_viz.html``.
PEAKS_SLIM_BPS = 10
#: ffmpeg resample target for peak computation.
PEAKS_FFMPEG_SAMPLE_RATE = 8000
#: Divisor mapping int16 PCM to ``[-1, 1]``.
PEAKS_PCM_NORMALIZER = 32768.0
#: On-disk schema version of the slim blob (and the HD doc it packs).
PEAKS_SCHEMA_VERSION = 3
#: Floor on the HD bucket count so very short clips still draw.
MIN_FULL_PEAK_BUCKETS = 100
#: Wall clock allowed for a whole-chapter decode.
FFMPEG_FULL_TIMEOUT = 300

_INT8_SCALE = 127


def bucket_pcm_minmax(samples, num_samples: int, num_buckets: int) -> list[list[float]]:
    """Bucket a PCM signal into ``num_buckets`` min/max pairs over ``[0, num_samples)``.

    Uses a float stride so the buckets exactly tile the sample range — every
    sample lands in exactly one bucket and the tail isn't dropped. Returns fewer
    buckets than requested only when ``num_samples < num_buckets``.
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


def compute_audio_peaks(
    audio_source: str,
    *,
    timeout: float = FFMPEG_FULL_TIMEOUT,
    min_buckets: int = MIN_FULL_PEAK_BUCKETS,
) -> dict | None:
    """HD peaks for a local file path or URL, or ``None`` when ffmpeg fails."""
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-i",
                audio_source,
                "-f",
                "s16le",
                "-ac",
                "1",
                "-ar",
                str(PEAKS_FFMPEG_SAMPLE_RATE),
                "-v",
                "quiet",
                "-",
            ],  # fmt: skip
            capture_output=True,
            timeout=timeout,
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
    num_buckets = max(min_buckets, int(duration_sec * PEAKS_BUCKETS_PER_SEC))
    peaks = bucket_pcm_minmax(samples, num_samples, num_buckets)
    return {"schema_version": PEAKS_SCHEMA_VERSION, "duration_ms": duration_ms, "peaks": peaks}


def decimate(peaks: np.ndarray, src_bps: int, dst_bps: int) -> np.ndarray:
    """Reduce density by min-of-mins / max-of-maxes over windows of ``factor``.

    Preserves the visual envelope — every input min/max contributes to its
    output bucket. A non-divisible tail folds into one final bucket.
    """
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

    ``mtime=0`` keeps the gzip member byte-identical for the same input so the
    CDN / browser cache key is stable across re-bakes that didn't change the
    payload.
    """
    if not isinstance(hd_doc, dict) or "peaks" not in hd_doc or "duration_ms" not in hd_doc:
        raise ValueError("pack_slim: expected dict with 'peaks' and 'duration_ms'")
    arr = np.asarray(hd_doc["peaks"], dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError(f"pack_slim: expected peaks shape (N, 2), got {arr.shape}")
    arr = decimate(arr, src_bps=PEAKS_BUCKETS_PER_SEC, dst_bps=target_bps)
    i8 = np.clip(np.round(arr * _INT8_SCALE), -_INT8_SCALE, _INT8_SCALE).astype(np.int8)
    doc = {
        "schema_version": PEAKS_SCHEMA_VERSION,
        "duration_ms": int(hd_doc["duration_ms"]),
        "q": "int8",
        "bps": target_bps,
        "n": int(i8.shape[0]),
        "peaks_b64": base64.b64encode(i8.tobytes()).decode("ascii"),
    }
    return gzip.compress(
        json.dumps(doc, separators=(",", ":")).encode("utf-8"), compresslevel=6, mtime=0
    )
