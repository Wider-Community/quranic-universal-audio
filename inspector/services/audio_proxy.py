"""Audio download/cache management.

No Flask imports -- all functions accept parameters and return plain dicts.
"""

import os
import shutil
import tempfile
import urllib.request
from pathlib import Path

from config import CACHE_DIR
from services import cache
from services.data_loader import load_detailed
from services.peaks import compute_audio_peaks
from utils.references import chapter_from_ref


def reciter_audio_total(reciter: str) -> int:
    """Return the number of unique audio URLs for a reciter."""
    entries = load_detailed(reciter)
    if not entries:
        return 0
    urls = set()
    for entry in entries:
        url = entry.get("audio", "")
        if url:
            urls.add(url)
    return len(urls)


def scan_audio_cache(reciter: str, force: bool = False) -> dict:
    """Scan reciter's cache directory.  Returns ``{cached_count, total, cached_bytes}``."""
    if not force:
        cached = cache.get_audio_cache_status(reciter)
        if cached is not None:
            return cached
    total = reciter_audio_total(reciter)
    reciter_dir = CACHE_DIR / reciter / "audio"
    cached_count = 0
    total_bytes = 0
    if reciter_dir.is_dir():
        for f in reciter_dir.iterdir():
            if f.is_file() and not f.name.startswith('.'):
                cached_count += 1
                try:
                    total_bytes += f.stat().st_size
                except OSError:
                    pass
    result = {"cached_count": cached_count, "total": total, "cached_bytes": total_bytes}
    cache.set_audio_cache_status(reciter, result)
    return result


def download_audio(reciter: str, url: str) -> Path | None:
    """Download audio from URL to disk cache, then compute peaks.

    Returns cache path or ``None``.
    """
    cache_path = cache.audio_cache_path(reciter, url)
    if not cache_path.exists():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd, tmp_name = tempfile.mkstemp(suffix=".mp3", dir=cache_path.parent)
            os.close(fd)
            tmp_path = Path(tmp_name)
            urllib.request.urlretrieve(url, tmp_path)
            os.replace(tmp_path, cache_path)
        except Exception as e:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            print(f"Audio download failed: {url}: {e}")
            return None
    # Compute peaks from local file, keyed by original URL for client lookup
    peaks_data = compute_audio_peaks(str(cache_path), cache_key=url, reciter=reciter)
    if peaks_data:
        cache.set_peaks_for_url(reciter, url, peaks_data)
    return cache_path


def delete_audio_cache(reciter: str) -> dict:
    """Delete all cached data (audio + peaks) for a reciter.

    Returns ``{deleted, freed_bytes}``.
    """
    reciter_dir = CACHE_DIR / reciter
    deleted = 0
    freed_bytes = 0
    if reciter_dir.is_dir():
        for f in reciter_dir.rglob("*"):
            if f.is_file():
                try:
                    freed_bytes += f.stat().st_size
                    f.unlink()
                    deleted += 1
                except OSError:
                    pass
        shutil.rmtree(reciter_dir, ignore_errors=True)
    lock = cache.get_audio_dl_lock()
    with lock:
        cache.pop_audio_dl_progress(reciter)
    cache.pop_audio_cache_status(reciter)
    cache.pop_peaks_cache(reciter)
    return {"deleted": deleted, "freed_bytes": freed_bytes}
