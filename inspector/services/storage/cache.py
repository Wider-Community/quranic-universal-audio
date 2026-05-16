"""Centralized cache registry for the inspector server.

Every mutable cache variable lives here with getter/setter/invalidation
functions.  No other module uses ``global`` for cache variables.
"""

import threading
from typing import Generic, TypeVar

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


# Timestamps tab — local-mode shard cache lives in `services/timestamps.py`
# (manifest + per-chapter gzipped bytes, lazy-built). Nothing for this tab
# is registered here: the legacy `_ts` / `_ts_reciters` slots that pinned
# full ``timestamps_full.json`` docs in memory are gone.


# Segments
_seg: _KeyedCache[list[dict]] = _KeyedCache()
_seg_meta: _KeyedCache[dict] = _KeyedCache()
_seg_verses: _KeyedCache[tuple] = _KeyedCache()
_seg_resolved_by_edit: _KeyedCache[dict[str, set[str]]] = _KeyedCache()
# Low-Confidence v2 sidecar — uid set + meta dict (or None when sidecar absent).
_seg_probe_v2: _KeyedCache[tuple[set[str], dict | None]] = _KeyedCache()
# Auto-Split sidecar — precomputed cursors/refs by uid, plus meta. Empty dict
# tuple member when sidecar absent so callers don't re-stat on every lookup.
_seg_auto_split: _KeyedCache[tuple[dict[str, dict], dict | None]] = _KeyedCache()
_seg_edit_history: _KeyedCache[dict] = _KeyedCache()
_seg_history_peaks: _KeyedCache[list[dict]] = _KeyedCache()
# Validation + stats results — recomputed only on cache miss; cleared by
# ``invalidate_seg_caches`` on every save / undo so writers can't read stale data.
_seg_validate_result: _KeyedCache[dict] = _KeyedCache()
_seg_stats_result: _KeyedCache[dict] = _KeyedCache()


def get_seg_cache(reciter: str) -> list[dict] | None:
    return _seg.get(reciter)


def set_seg_cache(reciter: str, entries: list[dict]) -> None:
    _seg.set(reciter, entries)


def get_seg_meta(reciter: str) -> dict:
    return _seg_meta.get(reciter) or {}


def set_seg_meta(reciter: str, meta: dict) -> None:
    _seg_meta.set(reciter, meta)


def get_seg_verses_cache(reciter: str):
    return _seg_verses.get(reciter)


def set_seg_verses_cache(reciter: str, data: tuple) -> None:
    _seg_verses.set(reciter, data)


def get_seg_resolved_by_edit(reciter: str) -> dict[str, set[str]] | None:
    return _seg_resolved_by_edit.get(reciter)


def set_seg_resolved_by_edit(reciter: str, index: dict[str, set[str]]) -> None:
    _seg_resolved_by_edit.set(reciter, index)


def get_seg_probe_v2(reciter: str) -> tuple[set[str], dict | None] | None:
    return _seg_probe_v2.get(reciter)


def set_seg_probe_v2(reciter: str, value: tuple[set[str], dict | None]) -> None:
    _seg_probe_v2.set(reciter, value)


def get_seg_auto_split(reciter: str) -> tuple[dict[str, dict], dict | None] | None:
    return _seg_auto_split.get(reciter)


def set_seg_auto_split(reciter: str, value: tuple[dict[str, dict], dict | None]) -> None:
    _seg_auto_split.set(reciter, value)


def get_seg_edit_history(reciter: str) -> dict | None:
    return _seg_edit_history.get(reciter)


def set_seg_edit_history(reciter: str, value: dict) -> None:
    _seg_edit_history.set(reciter, value)


def get_seg_history_peaks(reciter: str) -> list[dict] | None:
    return _seg_history_peaks.get(reciter)


def set_seg_history_peaks(reciter: str, value: list[dict]) -> None:
    _seg_history_peaks.set(reciter, value)


def get_seg_validate_cache(reciter: str) -> dict | None:
    return _seg_validate_result.get(reciter)


def set_seg_validate_cache(reciter: str, value: dict) -> None:
    _seg_validate_result.set(reciter, value)


def get_seg_stats_cache(reciter: str) -> dict | None:
    return _seg_stats_result.get(reciter)


def set_seg_stats_cache(reciter: str, value: dict) -> None:
    _seg_stats_result.set(reciter, value)


def invalidate_seg_caches(reciter: str) -> None:
    """Remove all segment-related caches for *reciter* and reset reciters list."""
    _seg.pop(reciter)
    _seg_meta.pop(reciter)
    _seg_verses.pop(reciter)
    _seg_resolved_by_edit.pop(reciter)
    _seg_probe_v2.pop(reciter)
    _seg_auto_split.pop(reciter)
    _seg_edit_history.pop(reciter)
    _seg_history_peaks.pop(reciter)
    _seg_validate_result.pop(reciter)
    _seg_stats_result.pop(reciter)


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
# Flat ``"surah:ayah:word" -> text`` projection of _dk, served to the FE so
# it can resolve ref → display text locally instead of round-tripping. Built
# once on first request.
_dk_words_flat: _SingletonCache[dict[str, str]] = _SingletonCache()


def get_qpc_cache():
    return _qpc.get()


def set_qpc_cache(data: dict) -> None:
    _qpc.set(data)


def get_dk_cache():
    return _dk.get()


def set_dk_cache(data: dict) -> None:
    _dk.set(data)


def get_dk_words_flat_cache():
    return _dk_words_flat.get()


def set_dk_words_flat_cache(data: dict[str, str]) -> None:
    _dk_words_flat.set(data)


# Surah info lite
_surah_info_lite: _SingletonCache[dict] = _SingletonCache()


def get_surah_info_lite_cache():
    return _surah_info_lite.get()


def set_surah_info_lite_cache(data: dict) -> None:
    _surah_info_lite.set(data)
