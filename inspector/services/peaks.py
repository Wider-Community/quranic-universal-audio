"""Waveform peak computation via ffmpeg.

No Flask imports -- all functions accept parameters and return plain dicts.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import struct
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

from config import (CACHE_DIR, FFMPEG_FULL_TIMEOUT, FFMPEG_TIMEOUT,
                    MIN_FULL_PEAK_BUCKETS, MIN_SEG_PEAK_BUCKETS,
                    PEAKS_BUCKETS_PER_SEC, PEAKS_FFMPEG_SAMPLE_RATE,
                    PEAKS_MIN_CHUNK_BYTES, PEAKS_PCM_NORMALIZER,
                    PEAKS_WORKER_COUNT, ID3_PROBE_BYTES,
                    ID3_PROBE_TIMEOUT, DEFAULT_BYTES_PER_SEC,
                    RANGE_DECODE_PAD_SEC, TEMP_AUDIO_SUFFIX)
from services import cache
from services.data_loader import load_detailed

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
# HTTP Range infrastructure for segment-level peak extraction
# ---------------------------------------------------------------------------

def _decode_synchsafe_int(b: bytes) -> int:
    """Decode a 4-byte ID3v2 synchsafe integer. Per ID3v2.3 §3.1 spec."""
    return (b[0] & 0x7F) << 21 | (b[1] & 0x7F) << 14 | (b[2] & 0x7F) << 7 | (b[3] & 0x7F)


def _get_audio_meta(url: str) -> dict:
    """Probe a remote MP3 URL for ID3v2 offset and approximate bytes_per_sec."""
    cached = cache.get_url_audio_meta(url)
    if cached is not None:
        return cached

    id3_offset = 0
    try:
        req = urllib.request.Request(url, headers={"Range": f"bytes=0-{ID3_PROBE_BYTES - 1}"})
        with urllib.request.urlopen(req, timeout=ID3_PROBE_TIMEOUT) as resp:
            header_data = resp.read(ID3_PROBE_BYTES)
            # Check for ID3v2 header: "ID3" magic bytes
            if len(header_data) >= 10 and header_data[:3] == b"ID3":
                # ID3v2 size is a synchsafe integer in bytes 6-9
                id3_offset = 10 + _decode_synchsafe_int(header_data[6:10])
    except Exception:
        pass

    # Estimate bytes_per_sec from ffprobe on a small chunk
    bytes_per_sec = DEFAULT_BYTES_PER_SEC
    try:
        req = urllib.request.Request(url, headers={"Range": f"bytes={id3_offset}-{id3_offset + ID3_PROBE_BYTES - 1}"})
        with urllib.request.urlopen(req, timeout=ID3_PROBE_TIMEOUT) as resp:
            probe_data = resp.read(ID3_PROBE_BYTES)
        fd, tmp_path = tempfile.mkstemp(suffix=TEMP_AUDIO_SUFFIX)
        try:
            os.write(fd, probe_data)
            os.close(fd)
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_streams", tmp_path],
                capture_output=True, timeout=ID3_PROBE_TIMEOUT,
            )
            if result.returncode == 0:
                streams = json.loads(result.stdout).get("streams", [])
                for s in streams:
                    br = int(s.get("bit_rate", 0))
                    if br > 0:
                        bytes_per_sec = br // 8
                        break
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    except Exception:
        pass

    meta = {"id3_offset": id3_offset, "bytes_per_sec": bytes_per_sec}
    cache.set_url_audio_meta(url, meta)
    return meta


def _range_decode_segment(url: str, start_sec: float, duration_sec: float,
                          meta: dict) -> bytes | None:
    """Download an HTTP Range byte-slice and decode to raw PCM via ffmpeg.

    CBR-only path: maps time → byte by ``bytes_per_sec * t`` then fetches a
    padded Range and trims with ffmpeg ``-ss``. Cheap (~0.4 s) but assumes
    constant bitrate. Use :func:`_ffmpeg_decode_segment` for VBR sources.
    """
    bps = meta["bytes_per_sec"]
    id3 = meta["id3_offset"]
    pad = RANGE_DECODE_PAD_SEC

    # Align to a round boundary for MP3 frame sync
    aligned_start = max(0, start_sec - pad)
    aligned_end = start_sec + duration_sec + pad
    byte_start = id3 + int(aligned_start * bps)
    byte_end = id3 + int(aligned_end * bps)

    try:
        req = urllib.request.Request(url, headers={"Range": f"bytes={byte_start}-{byte_end}"})
        with urllib.request.urlopen(req, timeout=FFMPEG_TIMEOUT) as resp:
            chunk = resp.read()
    except Exception:
        return None

    if len(chunk) < PEAKS_MIN_CHUNK_BYTES:
        return None

    # Write to temp file and decode with ffmpeg
    fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
    try:
        os.write(fd, chunk)
        os.close(fd)
        # Seek within the chunk to the exact target window, emitting exactly
        # `duration_sec` seconds of PCM. The byte-range pad exists only so
        # ffmpeg has enough context for MP3 frame sync — it must NOT leak into
        # the output, or downstream peaks will cover a longer range than
        # requested (mis-aligning every peak relative to [start_ms, end_ms]).
        seek_within = max(0, start_sec - aligned_start)
        result = subprocess.run(
            ["ffmpeg", "-ss", str(seek_within), "-i", tmp_path,
             "-t", str(duration_sec),
             "-f", "s16le", "-ac", "1",
             "-ar", str(PEAKS_FFMPEG_SAMPLE_RATE),
             "-v", "quiet", "-"],
            capture_output=True, timeout=FFMPEG_TIMEOUT,
        )
        if result.returncode != 0 or len(result.stdout) < 4:
            return None
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _ffmpeg_decode_segment(src: AudioSource, start_sec: float,
                           duration_sec: float) -> bytes | None:
    """VBR-safe segment decode from a local source (bucket bytes or disk).

    ffmpeg seeks by time (frame-aware) so this works for both VBR and CBR
    without the byte-arithmetic mis-estimate of :func:`_range_decode_segment`.
    Reads from stdin pipe when ``src.data`` is in memory, from disk when
    ``src.path`` is set. Never from a URL — the inspector image's ffmpeg has
    ``--disable-network``.
    """
    if not src.has_local_bytes:
        return None
    input_arg = str(src.path) if src.path is not None else "pipe:0"
    try:
        result = subprocess.run(
            ["ffmpeg", "-ss", str(start_sec), "-i", input_arg,
             "-t", str(duration_sec),
             "-f", "s16le", "-ac", "1",
             "-ar", str(PEAKS_FFMPEG_SAMPLE_RATE),
             "-v", "quiet", "-"],
            capture_output=True, timeout=FFMPEG_TIMEOUT,
            input=src.data if src.path is None else None,
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

    # Not cached -- decode via resolver (local bytes/path) or fall back to
    # HTTP Range arithmetic for CBR remote sources.
    start_sec = start_ms / 1000
    duration_sec = (end_ms - start_ms) / 1000

    from services import audio_source
    src = audio_source.resolve(reciter, url) if reciter else None
    if src and src.has_local_bytes:
        raw = _ffmpeg_decode_segment(src, start_sec, duration_sec)
    else:
        # No local bytes — ffmpeg can't fetch HTTPS in the stripped inspector
        # image. Range-decode via urllib (CBR-correct, VBR-approximate) is the
        # only remaining option. For VBR remote chapters this mis-estimates
        # by seconds on late segments; acceptable degraded fallback until the
        # prefetch worker has populated the bucket.
        meta = _get_audio_meta(url)
        raw = _range_decode_segment(url, start_sec, duration_sec, meta)
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
