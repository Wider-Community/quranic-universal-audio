"""Audio side of a sample upload: probe, normalise to MP3, bake slim peaks.

The Segments view expects ``audio/<chapter>.mp3`` plus ``peaks/<chapter>.json.gz``
under the sample folder, the same shape the extraction pipeline writes for
reciters. ``bake_peaks`` is the one place the app writes chapter peaks at
runtime; callers run it off the request thread (ffmpeg over a whole file).

No Flask imports — callable from a worker thread.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from config import FFMPEG_FULL_TIMEOUT
from services.audio.peaks import compute_audio_peaks
from services.audio.peaks_slim import pack_slim
from services.storage import storage_paths
from services.storage.hf_bucket import get_backend

logger = logging.getLogger(__name__)

MP3_TRANSCODE_BITRATE = "128k"
FFPROBE_TIMEOUT = 30


class AudioIngestError(RuntimeError):
    """ffprobe/ffmpeg could not read or convert the uploaded audio."""


def probe(path: Path) -> dict:
    """Return ``{duration_ms, bitrate_kbps, format}`` for a local audio file."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,bit_rate,format_name",
        "-of",
        "json",
        str(path),
    ]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=FFPROBE_TIMEOUT, check=True
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise AudioIngestError(f"ffprobe failed: {exc}") from exc
    fmt = (json.loads(out.stdout or "{}").get("format")) or {}
    try:
        duration_ms = int(float(fmt.get("duration", 0)) * 1000)
    except (TypeError, ValueError):
        duration_ms = 0
    if duration_ms <= 0:
        raise AudioIngestError("audio has no readable duration")
    try:
        bitrate_kbps = int(float(fmt.get("bit_rate", 0)) / 1000) or None
    except (TypeError, ValueError):
        bitrate_kbps = None
    return {
        "duration_ms": duration_ms,
        "bitrate_kbps": bitrate_kbps,
        "format": str(fmt.get("format_name") or ""),
    }


def normalize_to_mp3(src: Path, dst: Path) -> None:
    """Write ``dst`` as MP3 — stream-copy when ``src`` already is, else transcode."""
    is_mp3 = "mp3" in probe(src)["format"].split(",")
    codec = ["-c:a", "copy"] if is_mp3 else ["-c:a", "libmp3lame", "-b:a", MP3_TRANSCODE_BITRATE]
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", *codec, "-f", "mp3", str(dst)]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_FULL_TIMEOUT, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise AudioIngestError(f"ffmpeg failed: {detail.strip()[:300]}") from exc


def bake_peaks(mp3_path: Path, slug: str, chapter: int) -> None:
    """Compute HD peaks for the whole file and write the slim envelope to the bucket."""
    hd = compute_audio_peaks(str(mp3_path))
    if not hd:
        raise AudioIngestError("peaks computation produced nothing")
    get_backend().write_bytes_atomic(
        storage_paths.prefetched_peaks_path(slug, chapter), pack_slim(hd)
    )
