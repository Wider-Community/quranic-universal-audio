"""Waveform peak computation via ffmpeg.

No Flask imports -- all functions accept parameters and return plain dicts.
"""

from __future__ import annotations

import struct
import subprocess
from typing import TYPE_CHECKING

from config import (
    FFMPEG_TIMEOUT,
    MIN_SEG_PEAK_BUCKETS,
    PEAKS_BUCKETS_PER_SEC,
    PEAKS_FFMPEG_SAMPLE_RATE,
    PEAKS_SCHEMA_VERSION,
)
from qua_shared.audio.peaks import bucket_pcm_minmax as _shared_bucket_pcm_minmax
from qua_shared.audio.peaks import compute_audio_peaks as _shared_compute_audio_peaks

if TYPE_CHECKING:
    from services.audio_source import AudioSource


def is_current_schema(peaks: dict | None) -> bool:
    """True iff the peaks dict matches the current schema (``PEAKS_SCHEMA_VERSION``).

    History of bumps:

    - v1 → v2: bucketer fencepost fix. v1 computed
      ``block_size = num_samples // num_buckets``, truncating the trailing
      samples and leaving ``peaks.length × block_size`` short of
      ``num_samples``. The FE slices peaks against the advertised
      ``duration_ms``, so the missing tail manifested as a multiplicative
      time→peak drift on long chapters.
    - v2 → v3: on-disk shape change to the slim packed format
      (``services/audio/peaks_slim.py``). v3 blobs live at
      ``<chapter>.json.gz`` (not ``.json``) and the reader inflates them via
      ``unpack_slim`` before this check runs -- so what arrives here is still
      a dict with ``peaks: list[list[float]]`` plus ``schema_version=3``.

    A mismatched ``schema_version`` returns False, so the reader treats the
    blob as a cache miss and falls through to per-segment ffmpeg. Chapter
    peaks themselves are written offline only (Katana); the runtime never
    re-bakes them.
    """
    return isinstance(peaks, dict) and peaks.get("schema_version") == PEAKS_SCHEMA_VERSION


# Whole-chapter peaks are computed by ``qua_shared.audio.peaks`` (shared with
# the acquire HF Job so the baked ``peaks/<ch>.json.gz`` match what the runtime
# would produce); re-exported here for the app's callers.
_bucket_pcm_minmax = _shared_bucket_pcm_minmax
compute_audio_peaks = _shared_compute_audio_peaks


# ---------------------------------------------------------------------------
# Segment-level peak extraction
# ---------------------------------------------------------------------------


def _ffmpeg_decode_segment(
    src: AudioSource | None, url: str, start_sec: float, duration_sec: float
) -> bytes | None:
    """VBR-safe segment decode. Picks the cheapest available input for the
    requested window:

    * ``src.path`` (bucket mount) → ffmpeg reads the local file.
    * ``src.data`` (in-memory bucket bytes, local-dev no-mount only) → stdin.
    * ``url`` fallback → ffmpeg fetches the chapter via HTTP Range itself
      (frame-aware, VBR-correct). Requires the network-enabled ffmpeg build —
      see ``inspector/Dockerfile`` (``--enable-protocol=…,http,https,tcp,tls``).

    Returns raw mono 16-bit PCM at ``PEAKS_FFMPEG_SAMPLE_RATE``, or ``None``
    on ffmpeg failure / timeout.
    """
    stdin_data: bytes | None = None
    if src is not None and src.path is not None:
        input_arg = str(src.path)
    elif src is not None and src.data is not None:
        input_arg = "pipe:0"
        stdin_data = src.data
    else:
        input_arg = url
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-ss",
                str(start_sec),
                "-i",
                input_arg,
                "-t",
                str(duration_sec),
                "-f",
                "s16le",
                "-ac",
                "1",
                "-ar",
                str(PEAKS_FFMPEG_SAMPLE_RATE),
                "-v",
                "quiet",
                "-",
            ],
            capture_output=True,
            timeout=FFMPEG_TIMEOUT,
            input=stdin_data,
        )
        if result.returncode != 0 or len(result.stdout) < 4:
            return None
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def compute_segment_peaks(
    url: str,
    start_ms: int,
    end_ms: int,
    reciter: str | None = None,
    chapter: int | str | None = None,
    bps: int | None = None,
) -> dict | None:
    """Compute peaks for a specific segment time range via ffmpeg.

    Returns ``{schema_version, start_ms, end_ms, duration_ms, peaks}`` or
    ``None``. No caching — the caller is expected to be a one-shot live
    request when bucket chapter peaks are missing; bucket peaks themselves
    are produced offline and treated as the canonical store.

    ``bps`` (buckets per second) defaults to the HD ``PEAKS_BUCKETS_PER_SEC``
    (30) used by Segments-tab zoom + Timestamps. The History tab passes 10 to
    match the chapter overview + the persisted ``edit_history_peaks.jsonl``,
    making the fallback ~3× cheaper and the write-back record already-10 bps.
    """
    # Decode via resolver — local bytes / path when prefetched, otherwise
    # ffmpeg fetches the chapter via HTTP Range directly (frame-aware,
    # VBR-correct).
    start_sec = start_ms / 1000
    duration_sec = (end_ms - start_ms) / 1000

    from . import audio_source

    src = audio_source.resolve(reciter, url) if reciter else None
    raw = _ffmpeg_decode_segment(src, url, start_sec, duration_sec)
    if raw is None:
        return None

    num_samples = len(raw) // 2
    if num_samples == 0:
        return None
    samples = struct.unpack(f"<{num_samples}h", raw)

    actual_duration_ms = int(num_samples / PEAKS_FFMPEG_SAMPLE_RATE * 1000)
    eff_bps = bps if (isinstance(bps, int) and bps >= 1) else PEAKS_BUCKETS_PER_SEC
    num_buckets = max(MIN_SEG_PEAK_BUCKETS, int(duration_sec * eff_bps))
    peaks = _bucket_pcm_minmax(samples, num_samples, num_buckets)

    return {
        "schema_version": PEAKS_SCHEMA_VERSION,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "duration_ms": actual_duration_ms,
        "peaks": peaks,
    }
