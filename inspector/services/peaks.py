"""Waveform peak computation via ffmpeg.

No Flask imports -- all functions accept parameters and return plain dicts.
"""

import concurrent.futures
import hashlib
import json
import struct
import subprocess
from pathlib import Path

from config import CACHE_DIR, FFMPEG_FULL_TIMEOUT, MIN_FULL_PEAK_BUCKETS
from services import cache
from services.data_loader import load_detailed
from utils.references import chapter_from_ref


def peaks_cache_path(reciter: str, key: str) -> Path:
    """Return disk cache path for peaks JSON under the reciter's cache dir."""
    url_hash = hashlib.sha256(key.encode()).hexdigest()[:32]
    return CACHE_DIR / reciter / "peaks" / f"{url_hash}.json"


def compute_audio_peaks(audio_source: str, cache_key: str | None = None,
                        reciter: str | None = None) -> dict | None:
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

    # Decode to raw mono 16-bit PCM at 8kHz via ffmpeg
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", audio_source, "-f", "s16le", "-ac", "1", "-ar", "8000",
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

    duration_ms = int(num_samples / 8000 * 1000)
    duration_sec = num_samples / 8000
    num_buckets = max(MIN_FULL_PEAK_BUCKETS, int(duration_sec * 10))

    block_size = max(1, num_samples // num_buckets)
    peaks = []
    for i in range(num_buckets):
        start = i * block_size
        end = min(start + block_size, num_samples)
        if start >= num_samples:
            break
        block = samples[start:end]
        mn = min(block) / 32768.0
        mx = max(block) / 32768.0
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
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
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
