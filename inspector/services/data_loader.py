"""Data loading functions for timestamps, segments, audio URLs, and reference data.

All data is loaded once and cached via ``services.cache``.  Functions here never
import Flask -- they return plain dicts/lists.
"""

import json
from pathlib import Path

from config import (
    AUDIO_METADATA_PATH,
    DK_SCRIPT_PATH,
    QPC_HAFS_PATH,
    RECITATION_SEGMENTS_PATH,
    SURAH_INFO_PATH,
)
from adapters.detailed_json import load_entries as _load_detailed_entries
from constants import AUDIO_META_CATEGORIES, STOP_SIGNS
from services import cache
from utils.formatting import slug_to_name


# ---------------------------------------------------------------------------
# QPC / Digital Khatt
# ---------------------------------------------------------------------------

def load_qpc() -> dict[str, dict]:
    """Load and cache qpc_hafs.json."""
    cached = cache.get_qpc_cache()
    if cached is not None:
        return cached
    if QPC_HAFS_PATH.exists():
        import orjson
        data = orjson.loads(QPC_HAFS_PATH.read_bytes())
    else:
        data = {}
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

    Served to the FE on every chapter-data response so client-side
    ``dkTextForRef`` can build display text from a ref without an HTTP
    round-trip. Cached after first call.
    """
    cached = cache.get_dk_words_flat_cache()
    if cached is not None:
        return cached
    flat: dict[str, str] = {}
    for loc, entry in load_dk().items():
        text = entry.get("text") if isinstance(entry, dict) else None
        if text:
            flat[loc] = text
    cache.set_dk_words_flat_cache(flat)
    return flat


# Timestamps tab read path now lives in `services/ts_local.py` — see that
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
    seg_path = RECITATION_SEGMENTS_PATH / reciter / "segments.json"
    if not seg_path.exists():
        return {}, 0, 0, 0
    import orjson
    doc = orjson.loads(seg_path.read_bytes())
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
    path = RECITATION_SEGMENTS_PATH / reciter / "detailed.json"
    if not path.exists():
        return []
    meta, entries = _load_detailed_entries(path)
    if meta:
        cache.set_seg_meta(reciter, meta)
    cache.set_seg_cache(reciter, entries)
    # Fallback: if detailed.json had no _meta, try segments.json
    if not cache.get_seg_meta(reciter):
        seg_path = path.parent / "segments.json"
        if seg_path.exists():
            try:
                import orjson
                seg_doc = orjson.loads(seg_path.read_bytes())
                if "_meta" in seg_doc:
                    cache.set_seg_meta(reciter, seg_doc["_meta"])
            except Exception:
                pass
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
    path = RECITATION_SEGMENTS_PATH / reciter / "low_confidence_v2.json"
    if not path.exists():
        result: tuple[set[str], dict | None] = (set(), None)
        cache.set_seg_probe_v2(reciter, result)
        return result
    try:
        import orjson
        doc = orjson.loads(path.read_bytes())
    except Exception:
        result = (set(), None)
        cache.set_seg_probe_v2(reciter, result)
        return result
    failures = doc.get("failures") or []
    meta = doc.get("_meta") or None
    result = (set(failures), meta)
    cache.set_seg_probe_v2(reciter, result)
    return result


# Audio URL maps remain cached via `cache._audio_url`, but the only
# remaining caller is `routes/audio_metadata.py` (Audio tab), which now
# loads them inline. The Timestamps tab's old `load_audio_urls` flow is
# gone — `services/ts_local.py` inlines the per-chapter URL slice into
# each shard's `_meta` instead.


# ---------------------------------------------------------------------------
# Word counts and surah info
# ---------------------------------------------------------------------------

def get_word_counts() -> dict[tuple[int, int], int]:
    """Load and cache word counts from surah_info.json."""
    cached = cache.get_word_counts_cache()
    if cached is not None:
        return cached
    wc: dict[tuple[int, int], int] = {}
    sip = SURAH_INFO_PATH
    if not sip.exists():
        sip = RECITATION_SEGMENTS_PATH.parent / "surah_info.json"
    if sip.exists():
        import orjson
        si = orjson.loads(sip.read_bytes())
        for surah_str, data in si.items():
            for v in data["verses"]:
                wc[(int(surah_str), v["verse"])] = v["num_words"]
    cache.set_word_counts_cache(wc)
    return wc


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


# ---------------------------------------------------------------------------
# Audio sources (Audio tab)
# ---------------------------------------------------------------------------

def load_audio_sources() -> dict:
    """Walk ``data/audio/by_surah/<source>/`` and ``by_ayah/<source>/`` to build
    a hierarchical reciter index.
    """
    cached = cache.get_audio_sources_cache()
    if cached is not None:
        return cached
    result: dict[str, dict[str, list[dict]]] = {}
    if not AUDIO_METADATA_PATH.exists():
        cache.set_audio_sources_cache(result)
        return result
    for category in AUDIO_META_CATEGORIES:
        cat_dir = AUDIO_METADATA_PATH / category
        if not cat_dir.exists():
            continue
        cat_data: dict[str, list[dict]] = {}
        for source_dir in sorted(cat_dir.iterdir()):
            if not source_dir.is_dir():
                continue
            source = source_dir.name
            reciters = []
            for p in sorted(source_dir.glob("*.json")):
                slug = p.stem
                name = slug_to_name(slug)
                reciters.append({"slug": slug, "name": name})
            if reciters:
                cat_data[source] = reciters
        if cat_data:
            result[category] = cat_data
    cache.set_audio_sources_cache(result)
    return result
