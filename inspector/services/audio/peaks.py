"""Waveform peak computation via ffmpeg.

No Flask imports -- all functions accept parameters and return plain dicts.
"""

from __future__ import annotations

import concurrent.futures
import struct
import subprocess
from typing import TYPE_CHECKING

from config import (FFMPEG_FULL_TIMEOUT, FFMPEG_TIMEOUT,
                    MIN_FULL_PEAK_BUCKETS, MIN_SEG_PEAK_BUCKETS,
                    PEAKS_BUCKETS_PER_SEC, PEAKS_FFMPEG_SAMPLE_RATE,
                    PEAKS_PCM_NORMALIZER, PEAKS_SCHEMA_VERSION,
                    PEAKS_WORKER_COUNT)
from services.storage import cache
from services.storage.data_loader import load_detailed

if TYPE_CHECKING:
    from services.audio_source import AudioSource
from utils.references import chapter_from_ref


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

    Older versions return False so the cache miss triggers a re-bake via the
    prefetch fallback (``audio_fetch.fetch_and_persist_chapter``).
    """
    return isinstance(peaks, dict) and peaks.get("schema_version") == PEAKS_SCHEMA_VERSION


def _bucket_pcm_minmax(samples, num_samples: int, num_buckets: int) -> list[list[float]]:
    """Bucket a PCM signal into `num_buckets` min/max pairs over `[0, num_samples)`.

    Uses a float stride so the buckets exactly tile the sample range — every
    sample lands in exactly one bucket and the tail isn't dropped. Returns
    fewer buckets than requested only when `num_samples < num_buckets` (the
    per-bucket span rounds to zero), which lets very short clips fall
    through cleanly.
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
    """Compute waveform peaks for a local file path or URL.

    Returns ``{schema_version, duration_ms, peaks}`` or ``None``. No caching
    here and no bucket write — peaks are offline-computed and the bucket is
    treated as read-only at runtime. In-memory dedup lives in
    ``cache.update_peaks_cache`` for the lifetime of the process.
    """
    # Decode to raw mono 16-bit PCM via ffmpeg at the configured peaks sample rate
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", audio_source, "-f", "s16le", "-ac", "1",
             "-ar", str(PEAKS_FFMPEG_SAMPLE_RATE),
             "-v", "quiet", "-"],
            capture_output=True, timeout=FFMPEG_FULL_TIMEOUT,
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

    return {"schema_version": PEAKS_SCHEMA_VERSION, "duration_ms": duration_ms, "peaks": peaks}


# ---------------------------------------------------------------------------
# Segment-level peak extraction
# ---------------------------------------------------------------------------

def _ffmpeg_decode_segment(src: AudioSource | None, url: str,
                           start_sec: float, duration_sec: float) -> bytes | None:
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
            ["ffmpeg", "-ss", str(start_sec), "-i", input_arg,
             "-t", str(duration_sec),
             "-f", "s16le", "-ac", "1",
             "-ar", str(PEAKS_FFMPEG_SAMPLE_RATE),
             "-v", "quiet", "-"],
            capture_output=True, timeout=FFMPEG_TIMEOUT,
            input=stdin_data,
        )
        if result.returncode != 0 or len(result.stdout) < 4:
            return None
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def compute_segment_peaks(url: str, start_ms: int, end_ms: int,
                          reciter: str | None = None,
                          chapter: int | str | None = None) -> dict | None:
    """Compute peaks for a specific segment time range via ffmpeg.

    Returns ``{schema_version, start_ms, end_ms, duration_ms, peaks}`` or
    ``None``. No caching — the caller is expected to be a one-shot live
    request when bucket chapter peaks are missing; bucket peaks themselves
    are produced offline and treated as the canonical store.
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
    num_buckets = max(MIN_SEG_PEAK_BUCKETS, int(duration_sec * PEAKS_BUCKETS_PER_SEC))
    peaks = _bucket_pcm_minmax(samples, num_samples, num_buckets)

    return {
        "schema_version": PEAKS_SCHEMA_VERSION,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "duration_ms": actual_duration_ms,
        "peaks": peaks,
    }


def _audio_path_for_url(reciter: str, url: str) -> str | None:
    """Best local file path for an audio URL — bucket-mount only.

    Returns ``None`` when the bucket doesn't have the bytes; the caller skips
    compute (it would need to download via CDN, which is the chapter
    audio-proxy's responsibility, not the peaks worker's).
    """
    from . import audio_fetch
    try:
        bucket_local = audio_fetch.read_prefetched_audio_local_path(reciter, url)
    except Exception:  # noqa: BLE001
        bucket_local = None
    if bucket_local is not None:
        return str(bucket_local)
    return None


def get_peaks_for_reciter(reciter: str, chapter_filter: set[int] | None = None) -> dict:
    """Compute and cache peaks for a reciter's audio URLs.  Returns ``{url: peaks_data}``."""
    entries = load_detailed(reciter)
    if not entries:
        return {}

    urls = {}
    for entry in entries:
        chapter = chapter_from_ref(entry["ref"])
        if chapter_filter and chapter not in chapter_filter:
            continue
        url = entry.get("audio", "")
        if url and url not in urls:
            urls[url] = True

    # Check what's already cached in memory
    lock = cache.get_peaks_lock()
    with lock:
        cached = cache.get_peaks_cache(reciter)

    to_compute = [u for u in urls if u not in cached]
    if not to_compute:
        return {u: cached[u] for u in urls if u in cached}

    # Compute missing peaks in parallel
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=PEAKS_WORKER_COUNT) as pool:
        future_to_url = {}
        for u in to_compute:
            path = _audio_path_for_url(reciter, u)
            if path is None:
                continue
            future_to_url[pool.submit(compute_audio_peaks, path)] = u
        for future in concurrent.futures.as_completed(future_to_url):
            url = future_to_url[future]
            try:
                data = future.result()
                if data:
                    results[url] = data
            except Exception:
                pass

    all_cached = cache.update_peaks_cache(reciter, results)
    return {u: all_cached[u] for u in urls if u in all_cached}
