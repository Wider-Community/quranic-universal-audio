"""Centralized cache registry for the inspector server.

Every mutable cache variable lives here with getter/setter/invalidation
functions.  No other module uses ``global`` for cache variables.
"""

import hashlib
import threading
from pathlib import Path
from typing import Any, Generic, TypeVar

from config import CACHE_DIR, TEMP_AUDIO_SUFFIX

_T = TypeVar("_T")


class _SingletonCache(Generic[_T]):
    """Holds a single nullable value — replaces a bare ``global`` variable."""

    def __init__(self) -> None:
        self._value: _T | None = None

    def get(self) -> _T | None:
        return self._value

    def set(self, value: _T) -> None:
        self._value = value

    def clear(self) -> None:
        self._value = None


class _KeyedCache(Generic[_T]):
    """Holds a dict keyed by string — replaces a bare ``global`` dict."""

    def __init__(self) -> None:
        self._data: dict[str, _T] = {}

    def get(self, key: str) -> _T | None:
        return self._data.get(key)

    def set(self, key: str, value: _T) -> None:
        self._data[key] = value

    def pop(self, key: str) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()

    def all(self) -> dict[str, _T]:
        return self._data


# Timestamps
_ts: _KeyedCache[dict] = _KeyedCache()
_ts_reciters: _SingletonCache[list[dict]] = _SingletonCache()


def get_ts_cache(reciter: str) -> dict | None:
    return _ts.get(reciter)


def set_ts_cache(reciter: str, data: dict) -> None:
    _ts.set(reciter, data)


def get_all_ts_cache() -> dict[str, dict]:
    return _ts.all()


def get_ts_reciters_cache() -> list[dict] | None:
    return _ts_reciters.get()


def set_ts_reciters_cache(reciters: list[dict]) -> None:
    _ts_reciters.set(reciters)


# Segments
_seg: _KeyedCache[list[dict]] = _KeyedCache()
_seg_meta: _KeyedCache[dict] = _KeyedCache()
_seg_reciters: _SingletonCache[list[dict]] = _SingletonCache()
_seg_verses: _KeyedCache[tuple] = _KeyedCache()


def get_seg_cache(reciter: str) -> list[dict] | None:
    return _seg.get(reciter)


def set_seg_cache(reciter: str, entries: list[dict]) -> None:
    _seg.set(reciter, entries)


def get_seg_meta(reciter: str) -> dict:
    return _seg_meta.get(reciter) or {}


def set_seg_meta(reciter: str, meta: dict) -> None:
    _seg_meta.set(reciter, meta)


def get_seg_reciters_cache() -> list[dict] | None:
    return _seg_reciters.get()


def set_seg_reciters_cache(reciters: list[dict]) -> None:
    _seg_reciters.set(reciters)


def get_seg_verses_cache(reciter: str):
    return _seg_verses.get(reciter)


def set_seg_verses_cache(reciter: str, data: tuple) -> None:
    _seg_verses.set(reciter, data)


def invalidate_seg_caches(reciter: str) -> None:
    """Remove all segment-related caches for *reciter* and reset reciters list."""
    _seg.pop(reciter)
    _seg_meta.pop(reciter)
    _seg_verses.pop(reciter)
    _seg_reciters.clear()  # MUST be a full reset — not a per-reciter pop


# Peaks (thread-safe — manually coded)
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


# Remote audio meta (url -> {id3_offset, bytes_per_sec})
_url_audio_meta: _KeyedCache[dict] = _KeyedCache()


def get_url_audio_meta(url: str) -> dict | None:
    return _url_audio_meta.get(url)


def set_url_audio_meta(url: str, meta: dict) -> None:
    _url_audio_meta.set(url, meta)


# Phonemizer singleton
_phonemizer: _SingletonCache[Any] = _SingletonCache()


def get_phonemizer_singleton() -> Any:
    return _phonemizer.get()


def set_phonemizer_singleton(phonemizer: Any) -> None:
    _phonemizer.set(phonemizer)


# Canonical phonemes
_canonical_phonemes: _KeyedCache[dict[str, list[str]]] = _KeyedCache()


def get_canonical_phonemes_cache(reciter: str):
    return _canonical_phonemes.get(reciter)


def set_canonical_phonemes_cache(reciter: str, data: dict) -> None:
    _canonical_phonemes.set(reciter, data)


# Phoneme substitution pairs (lazy singleton)
_phoneme_sub_pairs: _SingletonCache[set[frozenset]] = _SingletonCache()


def get_phoneme_sub_pairs_cache():
    return _phoneme_sub_pairs.get()


def set_phoneme_sub_pairs_cache(pairs: set[frozenset]) -> None:
    _phoneme_sub_pairs.set(pairs)


# Audio URL
_audio_url: _KeyedCache[dict] = _KeyedCache()


def get_audio_url_cache(key: str) -> dict | None:
    return _audio_url.get(key)


def set_audio_url_cache(key: str, urls: dict) -> None:
    _audio_url.set(key, urls)


# Audio download / cache status (thread-safe)
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


# Word counts
_word_counts: _SingletonCache[dict[tuple[int, int], int]] = _SingletonCache()


def get_word_counts_cache():
    return _word_counts.get()


def set_word_counts_cache(wc: dict[tuple[int, int], int]) -> None:
    _word_counts.set(wc)


# Audio sources (Audio tab)
_audio_sources: _SingletonCache[dict] = _SingletonCache()


def get_audio_sources_cache():
    return _audio_sources.get()


def set_audio_sources_cache(sources: dict) -> None:
    _audio_sources.set(sources)


# QPC / DK data
_qpc: _SingletonCache[dict[str, dict]] = _SingletonCache()
_dk: _SingletonCache[dict[str, dict]] = _SingletonCache()


def get_qpc_cache():
    return _qpc.get()


def set_qpc_cache(data: dict) -> None:
    _qpc.set(data)


def get_dk_cache():
    return _dk.get()


def set_dk_cache(data: dict) -> None:
    _dk.set(data)


# Surah info lite
_surah_info_lite: _SingletonCache[dict] = _SingletonCache()


def get_surah_info_lite_cache():
    return _surah_info_lite.get()


def set_surah_info_lite_cache(data: dict) -> None:
    _surah_info_lite.set(data)


def audio_cache_path(reciter: str, url: str) -> Path:
    """Return disk cache path for an audio URL under the reciter's cache dir."""
    ext = Path(url.split("?")[0].split("#")[0]).suffix or TEMP_AUDIO_SUFFIX
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:32]
    return CACHE_DIR / reciter / "audio" / f"{url_hash}{ext}"
