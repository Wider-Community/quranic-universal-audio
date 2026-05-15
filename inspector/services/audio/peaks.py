"""Waveform peak computation via ffmpeg.

No Flask imports -- all functions accept parameters and return plain dicts.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import struct
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from config import (CACHE_DIR, FFMPEG_FULL_TIMEOUT, FFMPEG_TIMEOUT,
                    MIN_FULL_PEAK_BUCKETS, MIN_SEG_PEAK_BUCKETS,
                    PEAKS_BUCKETS_PER_SEC, PEAKS_FFMPEG_SAMPLE_RATE,
                    PEAKS_PCM_NORMALIZER, PEAKS_WORKER_COUNT)
from services.storage import cache
from services.storage.data_loader import load_detailed

if TYPE_CHECKING:
    from services.audio_source import AudioSource
from utils.references import chapter_from_ref


def peaks_cache_path(reciter: str, key: str) -> Path:
    """Return disk cache path for peaks JSON under the reciter's cache dir."""
    url_hash = hashlib.sha256(key.encode()).hexdigest()[:32]
    return CACHE_DIR / reciter / "peaks" / f"{url_hash}.json"


def compute_audio_peaks(audio_source: str, cache_key: str | None = None,
                        reciter: str | None = None, cached_only: bool = False) -> dict | None:
    """Compute waveform peaks for a local file path or URL.

    Returns ``{duration_ms, peaks}`` or ``None``.
    """
    key = cache_key or audio_source
    # Disk cache lookup
    cache_path = peaks_cache_path(reciter, key) if reciter else None
    if cache_path and cache_path.exists():
        try:
            with open(cache_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    if cached_only:
        return None

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

    block_size = max(1, num_samples // num_buckets)
    peaks = []
    for i in range(num_buckets):
        start = i * block_size
        end = min(start + block_size, num_samples)
        if start >= num_samples:
            break
        block = samples[start:end]
        mn = min(block) / PEAKS_PCM_NORMALIZER
        mx = max(block) / PEAKS_PCM_NORMALIZER
        peaks.append([round(mn, 4), round(mx, 4)])

    data = {"duration_ms": duration_ms, "peaks": peaks}

    # Write to disk cache
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, separators=(",", ":"))
        except OSError:
            pass

    return data


# ---------------------------------------------------------------------------
# Segment-level peak extraction
# ---------------------------------------------------------------------------

def _ffmpeg_decode_segment(src: AudioSource | None, url: str,
                           start_sec: float, duration_sec: float) -> bytes | None:
    """VBR-safe segment decode. Picks the cheapest available input for the
    requested window:

    * ``src.path`` (bucket mount or disk cache) → ffmpeg reads a local file.
    * ``src.data`` (in-memory bytes, local-dev only) → fed through stdin.
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
                          cached_only: bool = False,
                          chapter: int | str | None = None) -> dict | None:
    """Compute peaks for a specific segment time range via HTTP Range request.

    Returns ``{start_ms, end_ms, duration_ms, peaks}`` or ``None``.
    """
    cache_key = f"seg:{url}:{start_ms}:{end_ms}"
    cache_path = peaks_cache_path(reciter, cache_key) if reciter else None

    # Disk cache check
    if cache_path and cache_path.exists():
        try:
            with open(cache_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    if cached_only:
        return None

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
    block_size = max(1, num_samples // num_buckets)
    peaks = []
    for i in range(num_buckets):
        s = i * block_size
        e = min(s + block_size, num_samples)
        if s >= num_samples:
            break
        block = samples[s:e]
        mn = min(block) / PEAKS_PCM_NORMALIZER
        mx = max(block) / PEAKS_PCM_NORMALIZER
        peaks.append([round(mn, 4), round(mx, 4)])

    data = {
        "start_ms": start_ms,
        "end_ms": end_ms,
        "duration_ms": actual_duration_ms,
        "peaks": peaks,
    }

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, separators=(",", ":"))
        except OSError:
            pass

    return data


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
            local_path = cache.audio_cache_path(reciter, u)
            if not local_path.exists():
                continue
            future_to_url[pool.submit(compute_audio_peaks, str(local_path), u, reciter)] = u
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
