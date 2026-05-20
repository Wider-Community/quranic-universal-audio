"""Centralized cache registry for the inspector server.

Every mutable cache variable lives here with getter/setter/invalidation
functions.  No other module uses ``global`` for cache variables.
"""

import threading
from collections import OrderedDict
from typing import Generic, TypeVar

_T = TypeVar("_T")

# Per-cache LRU ceiling. The Inspector loads one reciter at a time in
# practice, but admin sweeps + concurrent reviewers can stack up; each
# parsed cache entry is small individually (~MB) but grows unboundedly
# across many reciters touched in one process lifetime. 20 covers the
# realistic concurrency ceiling on a single-worker Space with plenty of
# headroom while bounding worst-case RSS.
_KEYED_CACHE_LRU_MAX = 20


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
    """LRU-bounded dict keyed by string — replaces a bare ``global`` dict.

    Every ``set`` records the key as most-recently-used; once size exceeds
    ``_KEYED_CACHE_LRU_MAX``, the oldest entry is evicted. ``get`` does
    NOT promote a key — the loaders consult the cache once per request,
    and we want eviction to track write-time (the actual cost we're
    bounding) rather than read frequency.
    """

    def __init__(self, max_size: int = _KEYED_CACHE_LRU_MAX) -> None:
        self._data: "OrderedDict[str, _T]" = OrderedDict()
        self._max_size = max_size

    def get(self, key: str) -> _T | None:
        return self._data.get(key)

    def set(self, key: str, value: _T) -> None:
        if key in self._data:
            # Mark as most-recently-set so the new value isn't evicted next.
            self._data.move_to_end(key)
        self._data[key] = value
        while len(self._data) > self._max_size:
            self._data.popitem(last=False)

    def pop(self, key: str) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()

    def all(self) -> dict[str, _T]:
        return dict(self._data)


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
# pipeline_meta.json sidecar — extraction-time facts (deleted_basmala_chapters,
# generated_at, ...). Immutable post-extraction; NEVER invalidated by save.
_seg_pipeline_meta: _KeyedCache[dict] = _KeyedCache()
# Parsed edit_history.jsonl batches (list[dict]). Filled lazily on first read;
# every save APPENDS the new batch (no full re-parse). Undo also appends a
# revert batch. The cache slot itself is never popped on save/undo — only on
# process restart or explicit invalidation.
_seg_history_batches: _KeyedCache[list[dict]] = _KeyedCache()
# Derived index: uid → list of transitive split-descendant uids. Pure function
# of _seg_history_batches. Filled lazily; **extended on save** when the saved
# batch contains split_segment ops, **popped on undo** (revert negates prior
# ops; incremental append can't model removal — rebuild from cached list).
_seg_split_group_index: _KeyedCache[dict[str, list[str]]] = _KeyedCache()
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


def pop_seg_auto_split(reciter: str) -> None:
    """Pop the auto-split cache for *reciter*.

    Save's surgical-invalidate path (``pop_seg_caches_affected_by_segment_edit``)
    deliberately excludes this cache: split / merge / auto-fix / delete change
    the uid set so the cached cursors per uid become stale, but ref-edits and
    pure trims leave it valid. Callers gate the pop on
    ``batch_changes_segment_set(batch)``.
    """
    _seg_auto_split.pop(reciter)


def get_seg_pipeline_meta(reciter: str) -> dict | None:
    return _seg_pipeline_meta.get(reciter)


def set_seg_pipeline_meta(reciter: str, value: dict) -> None:
    _seg_pipeline_meta.set(reciter, value)


def pop_seg_pipeline_meta(reciter: str) -> None:
    """Explicit eviction (e.g. for the backfill script when it rewrites)."""
    _seg_pipeline_meta.pop(reciter)


# ---------------------------------------------------------------------------
# Edit-history-derived caches (incremental on save, pop+rebuild on undo)
# ---------------------------------------------------------------------------


def get_seg_history_batches(reciter: str) -> list[dict] | None:
    return _seg_history_batches.get(reciter)


def set_seg_history_batches(reciter: str, batches: list[dict]) -> None:
    _seg_history_batches.set(reciter, batches)


def append_history_batch(reciter: str, batch: dict) -> None:
    """Append a freshly-saved batch to the cached parsed list.

    No-op if the cache is empty for this reciter (next read will populate
    it from disk and naturally include the new batch). Save's append-then-
    notify ordering guarantees the batch is already on disk before this
    fires, so a cold reader sees a consistent picture either way.
    """
    cached = _seg_history_batches.get(reciter)
    if cached is None:
        return
    _seg_history_batches.set(reciter, [*cached, batch])


def pop_seg_history_batches(reciter: str) -> None:
    _seg_history_batches.pop(reciter)


def get_seg_split_group_index(reciter: str) -> dict[str, list[str]] | None:
    return _seg_split_group_index.get(reciter)


def set_seg_split_group_index(
    reciter: str, index: dict[str, list[str]],
) -> None:
    _seg_split_group_index.set(reciter, index)


def pop_seg_split_group_index(reciter: str) -> None:
    """Pop on undo — revert ops can't be modelled incrementally."""
    _seg_split_group_index.pop(reciter)


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
    """Remove all segment-related caches for *reciter* and reset reciters list.

    Deliberately does NOT touch:

    - The **peaks LRU response cache** — peaks files are tied to the audio
      bytes and never change as a side effect of edits, so the cached peaks
      response stays valid across any number of segment saves. Evicting it
      here would cost a ~500 ms cold miss on every autosave (every few
      seconds) for nothing. The LRU still naturally evicts under pressure
      (50-entry global ceiling) and on process restart.
    - The **pipeline_meta sidecar cache** — extraction-time facts that no
      user edit can change. Invalidating per save would burn the cache on
      every autosave for zero benefit.

    Add an explicit ``pop_reciter_peaks_response_cache`` call wherever a
    future code path actually rewrites peaks on the bucket; add an explicit
    ``pop_seg_pipeline_meta`` call wherever extraction or backfill rewrites
    the sidecar.
    """
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
    # _seg_history_batches and _seg_split_group_index are NOT popped here —
    # callers that mean it (save / undo) use the surgical helpers below so
    # the parsed list survives autosave warm paths.


def pop_seg_caches_affected_by_segment_edit(reciter: str) -> None:
    """Surgical eviction of caches a segment edit invalidates.

    Excludes:
    - ``_seg_pipeline_meta`` — extraction-time, immutable.
    - ``_seg_history_batches`` — appended in place (no re-parse).
    - ``_seg_split_group_index`` — extended in place on save; explicitly
      popped on undo via ``pop_seg_split_group_index``.
    - ``_seg_auto_split`` — only invalidated when the uid set changes;
      callers gate the pop on ``batch_changes_segment_set``.

    Callers should follow with ``append_history_batch`` (and, on save,
    ``set_seg_split_group_index`` to extend the index incrementally).
    """
    _seg.pop(reciter)
    _seg_meta.pop(reciter)
    _seg_verses.pop(reciter)
    _seg_resolved_by_edit.pop(reciter)
    _seg_probe_v2.pop(reciter)
    _seg_edit_history.pop(reciter)
    _seg_history_peaks.pop(reciter)
    _seg_validate_result.pop(reciter)
    _seg_stats_result.pop(reciter)


def batch_changes_segment_set(batch: dict) -> bool:
    """True when at least one op in ``batch`` mutates the seg uid set.

    Used to decide whether ``_seg_auto_split`` needs eviction — split / merge /
    auto-fix create new uids, trim / ref-edit do not.
    """
    _MUTATING_OPS = {
        "split_segment",
        "merge_segments",
        "auto_fix_missing_word",
        "delete_segment",
    }
    for op in batch.get("operations") or []:
        if op.get("op_type") in _MUTATING_OPS or op.get("kind") in _MUTATING_OPS:
            return True
    return False


# Peaks (thread-safe — manually coded)
_PEAKS_CACHE: dict[str, dict[str, dict]] = {}
_PEAKS_LOCK = threading.Lock()
def get_peaks_lock() -> threading.Lock:
    return _PEAKS_LOCK


def get_peaks_cache(reciter: str) -> dict[str, dict]:
    return _PEAKS_CACHE.get(reciter, {})


def set_peaks_for_url(reciter: str, url: str, data: dict) -> None:
    with _PEAKS_LOCK:
        if reciter not in _PEAKS_CACHE:
            _PEAKS_CACHE[reciter] = {}
        _PEAKS_CACHE[reciter][url] = data


# Peaks response cache — bounded-LRU for /api/seg/peaks GET responses.
#
# Keyed by (reciter, sorted_chapter_tuple). Value is the SERIALIZED JSON body
# (bytes) ready to send. Caching bytes (not the parsed dict) skips re-running
# jsonify on every hit -- for the worst chapter (husary ch2, 119k peak tuples)
# jsonify costs ~1.5-2s of single-worker CPU, so caching the dict and
# re-serializing made warm requests indistinguishable from cold ones in
# practice. Compression (flask-compress) runs on top of this, but the cache
# stays at the JSON-bytes layer so Vary/Accept-Encoding negotiation still
# works correctly per request.
#
# Eviction is global (not per-reciter) so we cap total RAM regardless of how
# many reciters a user browses in one session. ~50 entries × avg ~200 KiB
# uncompressed bytes ≈ ~10 MiB ceiling.
#
# Invalidated by reciter via ``pop_reciter_peaks_response_cache``, which is
# wired into ``invalidate_seg_caches`` -- save / undo flows drop every cached
# response for the edited reciter so the next request re-reads the bucket.
_PEAKS_RESPONSE_CACHE: "OrderedDict[tuple[str, tuple], bytes]" = OrderedDict()
_PEAKS_RESPONSE_MAX = 50
_PEAKS_RESPONSE_LOCK = threading.Lock()


def get_peaks_response_cache(reciter: str, chapters: tuple) -> bytes | None:
    """Return the cached serialized response bytes for ``(reciter, chapters)``."""
    key = (reciter, chapters)
    with _PEAKS_RESPONSE_LOCK:
        if key in _PEAKS_RESPONSE_CACHE:
            _PEAKS_RESPONSE_CACHE.move_to_end(key)  # LRU touch
            return _PEAKS_RESPONSE_CACHE[key]
    return None


def set_peaks_response_cache(reciter: str, chapters: tuple, value: bytes) -> None:
    """Store serialized response bytes. Evicts oldest entries when full."""
    key = (reciter, chapters)
    with _PEAKS_RESPONSE_LOCK:
        _PEAKS_RESPONSE_CACHE[key] = value
        _PEAKS_RESPONSE_CACHE.move_to_end(key)
        while len(_PEAKS_RESPONSE_CACHE) > _PEAKS_RESPONSE_MAX:
            _PEAKS_RESPONSE_CACHE.popitem(last=False)


def pop_reciter_peaks_response_cache(reciter: str) -> None:
    """Drop every cached response keyed by ``reciter`` (any chapter set)."""
    with _PEAKS_RESPONSE_LOCK:
        stale = [k for k in _PEAKS_RESPONSE_CACHE if k[0] == reciter]
        for k in stale:
            _PEAKS_RESPONSE_CACHE.pop(k, None)


def clear_peaks_response_cache() -> None:
    """Drop every cached response. Used by tests to prevent cross-test bleed."""
    with _PEAKS_RESPONSE_LOCK:
        _PEAKS_RESPONSE_CACHE.clear()


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


# Quran.Foundation Content API. Token is a single client_credentials grant
# shared process-wide ({access_token, expires_at}); chapter-URL maps are keyed
# by the QF chapter-reciter id (stringified). Content is immutable, so the
# only invalidation is the token's own TTL — no mutation hook needed.
_qf_content_token: _SingletonCache[dict] = _SingletonCache()
_qf_chapter_urls: _KeyedCache[dict] = _KeyedCache()
# Word-by-word translations, keyed by "<verse_key>|<language>" (e.g.
# "2:255|ur"). Content is immutable — no mutation hook, just LRU eviction.
_qf_wbw: _KeyedCache[dict] = _KeyedCache()


def get_qf_content_token() -> dict | None:
    return _qf_content_token.get()


def set_qf_content_token(token: dict) -> None:
    _qf_content_token.set(token)


def get_qf_chapter_urls(qf_reciter_id: str) -> dict | None:
    return _qf_chapter_urls.get(qf_reciter_id)


def set_qf_chapter_urls(qf_reciter_id: str, urls: dict) -> None:
    _qf_chapter_urls.set(qf_reciter_id, urls)


def get_qf_wbw(key: str) -> dict | None:
    return _qf_wbw.get(key)


def set_qf_wbw(key: str, words: dict) -> None:
    _qf_wbw.set(key, words)


# Audio manifest sidecar (catalog/audio_manifest/<slug>.json) + derived
# URL → chapter-key inverse index. Both populated together by
# ``services/audio/audio_meta._load_sidecar`` on first read. The inverse
# index turns ``chapter_for_url`` / ``chapter_meta_for_url`` from O(N)
# linear scans into O(1) dict lookups on the peaks fan-out hot path.
# Lifecycle matches every other per-reciter cache: LRU-bounded, popped by
# ``pop_audio_manifest_cache`` when a future probe-refresh path lands.
_audio_manifest: _KeyedCache[dict] = _KeyedCache()
_audio_manifest_url_index: _KeyedCache[dict[str, str]] = _KeyedCache()


def get_audio_manifest_cache(slug: str) -> dict | None:
    return _audio_manifest.get(slug)


def set_audio_manifest_cache(slug: str, doc: dict) -> None:
    _audio_manifest.set(slug, doc)


def pop_audio_manifest_cache(slug: str) -> None:
    _audio_manifest.pop(slug)
    _audio_manifest_url_index.pop(slug)


def get_audio_manifest_url_index_cache(slug: str) -> dict[str, str] | None:
    return _audio_manifest_url_index.get(slug)


def set_audio_manifest_url_index_cache(slug: str, idx: dict[str, str]) -> None:
    _audio_manifest_url_index.set(slug, idx)


# Audio cache status (thread-safe). Note: the audio download-progress dict
# (_AUDIO_DL_PROGRESS + helpers) lived here until the prefetch worker was
# removed; the sweeper that survives doesn't need progress tracking.
_AUDIO_CACHE_STATUS: dict[str, dict] = {}


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


# Single-word verses — derived from word_counts, computed once and cached
# alongside it. Used by the classifier's muqattaat / basmala_amin rules and
# the save-time persisted-classifier-fields stamp. Three callsites used to
# rebuild this O(6236) comprehension fresh each call; the singleton matches
# the lifetime of ``_word_counts`` (immutable post-boot).
_single_word_verses: _SingletonCache[set[tuple[int, int]]] = _SingletonCache()


def get_single_word_verses_cache():
    return _single_word_verses.get()


def set_single_word_verses_cache(swv: set[tuple[int, int]]) -> None:
    _single_word_verses.set(swv)


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
