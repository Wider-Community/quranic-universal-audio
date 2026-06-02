"""Data loading functions for timestamps, segments, audio URLs, and reference data.

All data is loaded once and cached via ``services.cache``. Functions here never
import Flask -- they return plain dicts/lists.

Per-reciter reads (``load_seg_verses``, ``load_detailed``, ``load_probe_v2``)
go through the storage backend via ``services.data_dir`` — no direct
filesystem access to ``RECITATION_SEGMENTS_PATH``. Static reference data
(qpc_hafs, surah_info, digital_khatt) still lives in the image at
``INSPECTOR_DATA_DIR`` and is read directly.
"""

from config import (
    DK_SCRIPT_PATH,
    SURAH_INFO_PATH,
)
from adapters.detailed_json import (
    load_entries_from_bytes as _load_detailed_entries_from_bytes,
)
from constants import STOP_SIGNS
from services.storage import cache, data_dir, static_refs
import threading

_detailed_locks: dict[str, threading.Lock] = {}
_detailed_locks_guard = threading.Lock()


def _detailed_lock(reciter: str) -> threading.Lock:
    with _detailed_locks_guard:
        lock = _detailed_locks.get(reciter)
        if lock is None:
            lock = threading.Lock()
            _detailed_locks[reciter] = lock
        return lock


# ---------------------------------------------------------------------------
# QPC / Digital Khatt
# ---------------------------------------------------------------------------

def load_qpc() -> dict[str, dict]:
    """Load and cache qpc_hafs.json.

    Byte resolution (local image → bucket) lives in
    ``services.storage.static_refs.load_qpc_bytes`` — on the deployed Space the
    image's ``.gz`` is an LFS pointer, so the real bytes come from the bucket.
    """
    cached = cache.get_qpc_cache()
    if cached is not None:
        return cached
    import orjson
    raw = static_refs.load_qpc_bytes()
    data = orjson.loads(raw) if raw else {}
    cache.set_qpc_cache(data)
    return data


def load_dk() -> dict[str, dict]:
    """Load and cache digital_khatt_v2_script.json."""
    cached = cache.get_dk_cache()
    if cached is not None:
        return cached
    if DK_SCRIPT_PATH.exists():
        import orjson
        data = orjson.loads(DK_SCRIPT_PATH.read_bytes())
    else:
        data = {}
    cache.set_dk_cache(data)
    return data


def get_dk_words_flat() -> dict[str, str]:
    """Flat ``"surah:ayah:word" -> text`` projection of ``load_dk()``.

    Promoted off per-request payloads to the immutable
    ``/api/static/quran-refs.json`` asset (see ``services/quran_refs.py``).
    Still consumed in-process by save / auto-split / validation. End-of-verse
    markers (``۝``) are stripped — ``dkTextForRef`` walks bounded by verse
    word counts and never indexes them, so they're dead weight.
    """
    cached = cache.get_dk_words_flat_cache()
    if cached is not None:
        return cached
    flat: dict[str, str] = {}
    for loc, entry in load_dk().items():
        text = entry.get("text") if isinstance(entry, dict) else None
        if text and not text.startswith("۝"):
            flat[loc] = text
    cache.set_dk_words_flat_cache(flat)
    return flat


# Timestamps tab read path now lives in `services/timestamps.py` — see that
# module for the manifest + per-chapter shard cache that replaced the
# eager `discover_ts_reciters` / `load_timestamps` loaders.


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------

def resolve_pad(meta: dict) -> tuple[int, int, int]:
    """Resolve VAD pad fields from ``_meta`` with alias-on-read.

    Returns ``(pad_left_ms, pad_right_ms, min_silence_floor_ms)``.

    For files written before asymmetric pad landed, ``pad_ms`` is
    treated as both left and right; ``min_silence_floor_ms`` defaults
    to 0 (no daylight guarantee was enforced pre-feature).
    """
    legacy = int(meta.get("pad_ms", 0))
    pad_left = int(meta.get("pad_left_ms", legacy))
    pad_right = int(meta.get("pad_right_ms", legacy))
    floor = int(meta.get("min_silence_floor_ms", 0))
    return pad_left, pad_right, floor


def load_seg_verses(reciter: str) -> tuple[dict, int, int, int]:
    """Load segments.json verse data for boundary mismatch checking.

    Returns ``(verses, pad_left_ms, pad_right_ms, min_silence_floor_ms)``.
    Cached.
    """
    cached = cache.get_seg_verses_cache(reciter)
    if cached is not None:
        return cached
    doc = data_dir.read_segments_doc(reciter)
    if doc is None:
        return {}, 0, 0, 0
    meta = doc.get("_meta", {})
    pad_left, pad_right, floor = resolve_pad(meta)
    verses = {k: v for k, v in doc.items() if k != "_meta"}
    result = (verses, pad_left, pad_right, floor)
    cache.set_seg_verses_cache(reciter, result)
    return result


def load_detailed(reciter: str) -> list[dict]:
    """Load and cache all entries from a reciter's detailed.json."""
    cached = cache.get_seg_cache(reciter)
    if cached is not None:
        return cached
    with _detailed_lock(reciter):
        cached = cache.get_seg_cache(reciter)
        if cached is not None:
            return cached
        raw = data_dir.read_detailed_bytes(reciter)
        if raw is None:
            return []
        meta, entries = _load_detailed_entries_from_bytes(raw)
        if meta:
            cache.set_seg_meta(reciter, meta)
        cache.set_seg_cache(reciter, entries)
        # Fallback: if detailed.json had no _meta, try segments.json
        if not cache.get_seg_meta(reciter):
            seg_doc = data_dir.read_segments_doc(reciter)
            if seg_doc and "_meta" in seg_doc:
                cache.set_seg_meta(reciter, seg_doc["_meta"])
        return entries


def load_probe_v2(reciter: str) -> tuple[set[str], dict | None]:
    """Load ``low_confidence_v2.json`` sidecar for *reciter*.

    Returns ``(failed_uid_set, meta_dict)``. When the sidecar is absent
    returns ``(set(), None)`` and caches the empty result so repeated
    lookups don't re-stat the filesystem. The sidecar is the source of
    truth for the *Low Confidence v2* validation category and is never
    written from the Inspector — it's emitted by the segments-stage
    MFA probe (``scripts/lib/probe_mfa.py``).
    """
    cached = cache.get_seg_probe_v2(reciter)
    if cached is not None:
        return cached
    doc = data_dir.read_low_confidence_doc(reciter)
    if doc is None:
        result: tuple[set[str], dict | None] = (set(), None)
        cache.set_seg_probe_v2(reciter, result)
        return result
    failures = doc.get("failures") or []
    meta = doc.get("_meta") or None
    result = (set(failures), meta)
    cache.set_seg_probe_v2(reciter, result)
    return result


def load_pipeline_meta(reciter: str) -> dict | None:
    """Load ``pipeline_meta.json`` for *reciter* (immutable post-extraction).

    Returns the validated ``PipelineMeta`` dict, or ``None`` if the sidecar
    is missing. The cache is **never invalidated by save** — the sidecar
    records extraction-time facts that no user edit can change.

    Callers that depend on a field (e.g. ``deleted_basmala_chapters``) should
    hard-fail on ``None`` rather than silently substituting an empty set;
    missing sidecar means the backfill script hasn't run for this reciter.
    """
    from scripts.lib.schemas import PipelineMeta

    cached = cache.get_seg_pipeline_meta(reciter)
    if cached is not None:
        return cached
    doc = data_dir.read_pipeline_meta_doc(reciter)
    if doc is None:
        return None
    validated = PipelineMeta.model_validate(doc).model_dump(mode="json")
    cache.set_seg_pipeline_meta(reciter, validated)
    return validated


def load_auto_split(reciter: str) -> tuple[dict[str, dict], dict | None]:
    """Load ``auto_split_v1.json`` sidecar for *reciter*.

    Returns ``(by_uid_map, meta_dict)`` where each value in ``by_uid_map`` is
    ``{"cursors": [int, ...], "refs": [str, ...], "kind": "cross_verse" |
    "repetition"}``. Empty dict + None when the sidecar is absent — that
    signals to the FE that every Auto Split candidate should fall back to
    the plain Split button (manual single-cursor placement). The sidecar is
    emitted offline by ``scripts/lib/auto_split_precompute.py``; the
    Inspector never writes it.
    """
    cached = cache.get_seg_auto_split(reciter)
    if cached is not None:
        return cached
    doc = data_dir.read_auto_split_doc(reciter)
    if doc is None:
        result: tuple[dict[str, dict], dict | None] = ({}, None)
        cache.set_seg_auto_split(reciter, result)
        return result
    by_uid = doc.get("by_uid") or {}
    meta = doc.get("_meta") or None
    if not isinstance(by_uid, dict):
        by_uid = {}
    result = (by_uid, meta)
    cache.set_seg_auto_split(reciter, result)
    return result


# Audio URL maps remain cached via `cache._audio_url`, but the only
# remaining caller is `routes/audio_metadata.py` (Audio tab), which now
# loads them inline. The Timestamps tab's old `load_audio_urls` flow is
# gone — `services/timestamps.py` inlines the per-chapter URL slice into
# each shard's `_meta` instead.


# ---------------------------------------------------------------------------
# Word counts and surah info
# ---------------------------------------------------------------------------

def get_word_counts() -> dict[tuple[int, int], int]:
    """Load and cache word counts from surah_info.json.

    Also primes ``cache.set_single_word_verses_cache`` with the derived
    ``{(surah, ayah): wc == 1}`` set so classifier / save callers don't
    rebuild it per call.
    """
    cached = cache.get_word_counts_cache()
    if cached is not None:
        return cached
    wc: dict[tuple[int, int], int] = {}
    if SURAH_INFO_PATH.exists():
        import orjson
        si = orjson.loads(SURAH_INFO_PATH.read_bytes())
        for surah_str, data in si.items():
            for v in data["verses"]:
                wc[(int(surah_str), v["verse"])] = v["num_words"]
    cache.set_word_counts_cache(wc)
    cache.set_single_word_verses_cache({k for k, v in wc.items() if v == 1})
    return wc


def get_single_word_verses() -> set[tuple[int, int]]:
    """Singleton set of ``(surah, ayah)`` keys whose verse has exactly one word.

    Derived from ``get_word_counts()`` once at first read; cached for the
    process lifetime alongside word_counts (both immutable post-boot).
    """
    cached = cache.get_single_word_verses_cache()
    if cached is not None:
        return cached
    # Force compute via get_word_counts (which primes the swv cache).
    get_word_counts()
    return cache.get_single_word_verses_cache() or set()


def load_surah_info_lite() -> dict:
    """Load lightweight surah metadata: number -> {name_en, name_ar, num_verses}."""
    cached = cache.get_surah_info_lite_cache()
    if cached is not None:
        return cached
    import orjson
    raw = orjson.loads(SURAH_INFO_PATH.read_bytes())
    result = {}
    for num, info in raw.items():
        result[num] = {
            "name_en": info.get("name_en", ""),
            "name_ar": info.get("name_ar", ""),
            "num_verses": info["num_verses"],
        }
    cache.set_surah_info_lite_cache(result)
    return result


def word_has_stop(surah: int, ayah: int, word_num: int) -> bool:
    """Check if a word in qpc_hafs.json contains a waqf stop sign."""
    qpc = load_qpc()
    entry = qpc.get(f"{surah}:{ayah}:{word_num}")
    if not entry:
        return False
    return bool(STOP_SIGNS & set(entry.get("text", "")))
