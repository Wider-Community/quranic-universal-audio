"""Centralized cache registry for the inspector server.

Every mutable cache variable lives here with getter/setter/invalidation
functions.  No other module uses ``global`` for cache variables.
"""

import hashlib
import threading
from pathlib import Path
from typing import Any

from config import CACHE_DIR

# ---------------------------------------------------------------------------
# Timestamps caches
# ---------------------------------------------------------------------------

_TS_CACHE: dict[str, dict] = {}  # reciter -> {meta, verses, audio_category}
_TS_RECITERS_CACHE: list[dict] | None = None


def get_ts_cache(reciter: str) -> dict | None:
    return _TS_CACHE.get(reciter)


def set_ts_cache(reciter: str, data: dict) -> None:
    _TS_CACHE[reciter] = data


def get_all_ts_cache() -> dict[str, dict]:
    return _TS_CACHE


def get_ts_reciters_cache() -> list[dict] | None:
    return _TS_RECITERS_CACHE


def set_ts_reciters_cache(reciters: list[dict]) -> None:
    global _TS_RECITERS_CACHE
    _TS_RECITERS_CACHE = reciters


# ---------------------------------------------------------------------------
# Segments caches
# ---------------------------------------------------------------------------

_SEG_CACHE: dict[str, list[dict]] = {}
_SEG_META_CACHE: dict[str, dict] = {}
_SEG_RECITERS_CACHE: list[dict] | None = None
_SEG_VERSES_CACHE: dict[str, tuple] = {}  # reciter -> (verses_dict, pad_ms)


def get_seg_cache(reciter: str) -> list[dict] | None:
    return _SEG_CACHE.get(reciter)


def set_seg_cache(reciter: str, entries: list[dict]) -> None:
    _SEG_CACHE[reciter] = entries


def get_seg_meta(reciter: str) -> dict:
    return _SEG_META_CACHE.get(reciter, {})


def set_seg_meta(reciter: str, meta: dict) -> None:
    _SEG_META_CACHE[reciter] = meta


def get_seg_reciters_cache() -> list[dict] | None:
    return _SEG_RECITERS_CACHE


def set_seg_reciters_cache(reciters: list[dict]) -> None:
    global _SEG_RECITERS_CACHE
    _SEG_RECITERS_CACHE = reciters


def get_seg_verses_cache(reciter: str):
    return _SEG_VERSES_CACHE.get(reciter)


def set_seg_verses_cache(reciter: str, data: tuple) -> None:
    _SEG_VERSES_CACHE[reciter] = data


def invalidate_seg_caches(reciter: str) -> None:
    """Remove all segment-related caches for *reciter* and reset reciters list."""
    global _SEG_RECITERS_CACHE
    _SEG_CACHE.pop(reciter, None)
    _SEG_META_CACHE.pop(reciter, None)
    _SEG_VERSES_CACHE.pop(reciter, None)
    _SEG_RECITERS_CACHE = None  # MUST reset to None, not just pop


# ---------------------------------------------------------------------------
# Peaks caches
# ---------------------------------------------------------------------------

_PEAKS_CACHE: dict[str, dict[str, dict]] = {}
_PEAKS_LOCK = threading.Lock()
_PEAKS_COMPUTING: set[str] = set()


def get_peaks_lock() -> threading.Lock:
    return _PEAKS_LOCK


def get_peaks_cache(reciter: str) -> dict[str, dict]:
    return _PEAKS_CACHE.get(reciter, {})


def set_peaks_for_url(reciter: str, url: str, data: dict) -> None:
    with _PEAKS_LOCK:
        if reciter not in _PEAKS_CACHE:
            _PEAKS_CACHE[reciter] = {}
        _PEAKS_CACHE[reciter][url] = data


def update_peaks_cache(reciter: str, new_data: dict[str, dict]) -> dict[str, dict]:
    """Merge *new_data* into the peaks cache for *reciter*. Returns the full cache."""
    with _PEAKS_LOCK:
        if reciter not in _PEAKS_CACHE:
            _PEAKS_CACHE[reciter] = {}
        _PEAKS_CACHE[reciter].update(new_data)
        return dict(_PEAKS_CACHE[reciter])


def pop_peaks_cache(reciter: str) -> None:
    _PEAKS_CACHE.pop(reciter, None)


def is_peaks_computing(key: str) -> bool:
    return key in _PEAKS_COMPUTING


def add_peaks_computing(key: str) -> None:
    _PEAKS_COMPUTING.add(key)


def discard_peaks_computing(key: str) -> None:
    _PEAKS_COMPUTING.discard(key)


# ---------------------------------------------------------------------------
# Remote audio meta cache (MP3 ID3 probing for HTTP Range segment-peaks)
# ---------------------------------------------------------------------------

# url -> {id3_offset: int, bytes_per_sec: int}. Absorbed from
# services/peaks.py in Wave 1 of Stage 2 so the `global` keyword never
# leaks outside this module.
_URL_AUDIO_META: dict[str, dict] = {}


def get_url_audio_meta(url: str) -> dict | None:
    return _URL_AUDIO_META.get(url)


def set_url_audio_meta(url: str, meta: dict) -> None:
    _URL_AUDIO_META[url] = meta


# ---------------------------------------------------------------------------
# Phonemizer singleton
# ---------------------------------------------------------------------------

# The `quranic_phonemizer.Phonemizer` instance is built lazily on first use
# and kept here. Typed as ``Any`` because the phonemizer package is an
# optional dependency — introducing a hard import to this module would
# regress the graceful-degradation behavior in
# ``services/phonemizer_service.py``.
_PHONEMIZER_SINGLETON: Any = None


def get_phonemizer_singleton() -> Any:
    return _PHONEMIZER_SINGLETON


def set_phonemizer_singleton(phonemizer: Any) -> None:
    global _PHONEMIZER_SINGLETON
    _PHONEMIZER_SINGLETON = phonemizer


# ---------------------------------------------------------------------------
# Canonical phonemes cache
# ---------------------------------------------------------------------------

_CANONICAL_PHONEMES_CACHE: dict[str, dict[str, list[str]]] = {}


def get_canonical_phonemes_cache(reciter: str):
    return _CANONICAL_PHONEMES_CACHE.get(reciter)


def set_canonical_phonemes_cache(reciter: str, data: dict) -> None:
    _CANONICAL_PHONEMES_CACHE[reciter] = data


# ---------------------------------------------------------------------------
# Phoneme substitution pairs (lazy singleton)
# ---------------------------------------------------------------------------

_PHONEME_SUB_PAIRS: set[frozenset] | None = None


def get_phoneme_sub_pairs_cache():
    return _PHONEME_SUB_PAIRS


def set_phoneme_sub_pairs_cache(pairs: set[frozenset]) -> None:
    global _PHONEME_SUB_PAIRS
    _PHONEME_SUB_PAIRS = pairs


# ---------------------------------------------------------------------------
# Audio URL cache
# ---------------------------------------------------------------------------

_AUDIO_URL_CACHE: dict[str, dict] = {}


def get_audio_url_cache(key: str) -> dict | None:
    return _AUDIO_URL_CACHE.get(key)


def set_audio_url_cache(key: str, urls: dict) -> None:
    _AUDIO_URL_CACHE[key] = urls


# ---------------------------------------------------------------------------
# Audio download / cache status
# ---------------------------------------------------------------------------

_AUDIO_DL_LOCK = threading.Lock()
_AUDIO_DL_PROGRESS: dict[str, dict] = {}
_AUDIO_CACHE_STATUS: dict[str, dict] = {}


def get_audio_dl_lock() -> threading.Lock:
    return _AUDIO_DL_LOCK


def get_audio_dl_progress(reciter: str) -> dict | None:
    return _AUDIO_DL_PROGRESS.get(reciter)


def set_audio_dl_progress(reciter: str, progress: dict) -> None:
    _AUDIO_DL_PROGRESS[reciter] = progress


def pop_audio_dl_progress(reciter: str) -> None:
    _AUDIO_DL_PROGRESS.pop(reciter, None)


def get_audio_cache_status(reciter: str) -> dict | None:
    return _AUDIO_CACHE_STATUS.get(reciter)


def set_audio_cache_status(reciter: str, status: dict) -> None:
    _AUDIO_CACHE_STATUS[reciter] = status


def pop_audio_cache_status(reciter: str) -> None:
    _AUDIO_CACHE_STATUS.pop(reciter, None)


# ---------------------------------------------------------------------------
# Word counts cache
# ---------------------------------------------------------------------------

_WORD_COUNTS_CACHE: dict[tuple[int, int], int] | None = None


def get_word_counts_cache():
    return _WORD_COUNTS_CACHE


def set_word_counts_cache(wc: dict[tuple[int, int], int]) -> None:
    global _WORD_COUNTS_CACHE
    _WORD_COUNTS_CACHE = wc


# ---------------------------------------------------------------------------
# Audio sources cache (Audio tab)
# ---------------------------------------------------------------------------

_AUDIO_SOURCES: dict | None = None


def get_audio_sources_cache():
    return _AUDIO_SOURCES


def set_audio_sources_cache(sources: dict) -> None:
    global _AUDIO_SOURCES
    _AUDIO_SOURCES = sources


# ---------------------------------------------------------------------------
# QPC / DK data caches
# ---------------------------------------------------------------------------

_QPC: dict[str, dict] | None = None
_DK: dict[str, dict] | None = None


def get_qpc_cache():
    return _QPC


def set_qpc_cache(data: dict) -> None:
    global _QPC
    _QPC = data


def get_dk_cache():
    return _DK


def set_dk_cache(data: dict) -> None:
    global _DK
    _DK = data


# ---------------------------------------------------------------------------
# Surah info lite cache
# ---------------------------------------------------------------------------

_SURAH_INFO_LITE: dict | None = None


def get_surah_info_lite_cache():
    return _SURAH_INFO_LITE


def set_surah_info_lite_cache(data: dict) -> None:
    global _SURAH_INFO_LITE
    _SURAH_INFO_LITE = data


# ---------------------------------------------------------------------------
# Shared path helper (used by both peaks and audio_proxy)
# ---------------------------------------------------------------------------

def audio_cache_path(reciter: str, url: str) -> Path:
    """Return disk cache path for an audio URL under the reciter's cache dir."""
    ext = Path(url.split("?")[0].split("#")[0]).suffix or ".mp3"
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:32]
    return CACHE_DIR / reciter / "audio" / f"{url_hash}{ext}"
