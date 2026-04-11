"""Data loading functions for timestamps, segments, audio URLs, and reference data.

All data is loaded once and cached via ``services.cache``.  Functions here never
import Flask -- they return plain dicts/lists.
"""

import json
import re
from pathlib import Path

from config import (
    AUDIO_METADATA_PATH,
    MAX_AYAH_BOUNDARY_CHECK,
    METADATA_PEEK_BYTES,
    RECITATION_SEGMENTS_PATH,
    SURAH_INFO_PATH,
    TIMESTAMPS_PATH,
)
from constants import STOP_SIGNS
from services import cache
from utils.references import chapter_from_ref

# Paths for QPC / DK data
_QPC_PATH = Path(__file__).resolve().parent.parent.parent / "quranic_universal_aligner" / "data" / "qpc_hafs.json"
_DK_PATH = Path(__file__).resolve().parent.parent.parent / "quranic_universal_aligner" / "data" / "digital_khatt_v2_script.json"


# ---------------------------------------------------------------------------
# QPC / Digital Khatt
# ---------------------------------------------------------------------------

def load_qpc() -> dict[str, dict]:
    """Load and cache qpc_hafs.json."""
    cached = cache.get_qpc_cache()
    if cached is not None:
        return cached
    if _QPC_PATH.exists():
        with open(_QPC_PATH, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}
    cache.set_qpc_cache(data)
    return data


def load_dk() -> dict[str, dict]:
    """Load and cache digital_khatt_v2_script.json."""
    cached = cache.get_dk_cache()
    if cached is not None:
        return cached
    if _DK_PATH.exists():
        with open(_DK_PATH, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}
    cache.set_dk_cache(data)
    return data


def dk_text_for_ref(ref: str) -> str:
    """Build Digital Khatt display text for a matched_ref like ``'1:7:1-1:7:5'``."""
    if not ref:
        return ""
    dk = load_dk()
    if not dk:
        return ""
    parts = ref.split("-")
    if len(parts) != 2:
        return ""
    start_parts = parts[0].split(":")
    end_parts = parts[1].split(":")
    if len(start_parts) != 3 or len(end_parts) != 3:
        return ""
    try:
        s_su, s_ay, s_w = int(start_parts[0]), int(start_parts[1]), int(start_parts[2])
        e_su, e_ay, e_w = int(end_parts[0]), int(end_parts[1]), int(end_parts[2])
    except ValueError:
        return ""
    wc = get_word_counts()
    words = []
    su, ay, w = s_su, s_ay, s_w
    while (su, ay, w) <= (e_su, e_ay, e_w):
        entry = dk.get(f"{su}:{ay}:{w}")
        if entry:
            words.append(entry["text"])
        w += 1
        if w > wc.get((su, ay), 0):
            w = 1
            ay += 1
            if ay > MAX_AYAH_BOUNDARY_CHECK:
                break
    return " ".join(words)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

def discover_ts_reciters() -> list[dict]:
    """Scan timestamps directories for reciters.  Cached after first call."""
    cached = cache.get_ts_reciters_cache()
    if cached is not None:
        return cached
    if not TIMESTAMPS_PATH.exists():
        cache.set_ts_reciters_cache([])
        return []
    result = []
    ts_all = cache.get_all_ts_cache()
    for category in ("by_ayah_audio", "by_surah_audio"):
        cat_dir = TIMESTAMPS_PATH / category
        if not cat_dir.is_dir():
            continue
        for reciter_dir in sorted(cat_dir.iterdir()):
            if not reciter_dir.is_dir():
                continue
            ts_file = reciter_dir / "timestamps_full.json"
            if not ts_file.exists():
                ts_file = reciter_dir / "timestamps.json"
                if not ts_file.exists():
                    continue
            slug = reciter_dir.name
            name = slug.replace("_", " ").title()
            audio_source = ""
            if slug in ts_all:
                audio_source = ts_all[slug].get("meta", {}).get("audio_source", "")
            else:
                try:
                    with open(ts_file, encoding="utf-8") as f:
                        head = f.read(METADATA_PEEK_BYTES)
                    m = re.search(r'"audio_source"\s*:\s*"([^"]*)"', head)
                    if m:
                        audio_source = m.group(1)
                except OSError:
                    pass
            result.append({
                "slug": slug, "name": name,
                "audio_source": audio_source,
                "audio_category": category,
            })
    cache.set_ts_reciters_cache(result)
    return result


def load_timestamps(reciter: str) -> dict:
    """Load and cache a reciter's verse-keyed timestamps JSON."""
    cached = cache.get_ts_cache(reciter)
    if cached is not None:
        return cached
    path = None
    for category in ("by_ayah_audio", "by_surah_audio"):
        full = TIMESTAMPS_PATH / category / reciter / "timestamps_full.json"
        basic = TIMESTAMPS_PATH / category / reciter / "timestamps.json"
        if full.exists():
            path = full
            break
        if basic.exists():
            path = basic
            break
    if path is None:
        return {}
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    meta = doc.pop("_meta", {})
    verses = doc
    result = {"meta": meta, "verses": verses, "audio_category": category}
    cache.set_ts_cache(reciter, result)
    return result


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------

def load_seg_verses(reciter: str) -> tuple[dict, int]:
    """Load segments.json verse data for boundary mismatch checking.  Cached."""
    cached = cache.get_seg_verses_cache(reciter)
    if cached is not None:
        return cached
    seg_path = RECITATION_SEGMENTS_PATH / reciter / "segments.json"
    if not seg_path.exists():
        return {}, 0
    with open(seg_path, encoding="utf-8") as f:
        doc = json.load(f)
    pad_ms = doc.get("_meta", {}).get("pad_ms", 0)
    verses = {k: v for k, v in doc.items() if k != "_meta"}
    cache.set_seg_verses_cache(reciter, (verses, pad_ms))
    return verses, pad_ms


def load_detailed(reciter: str) -> list[dict]:
    """Load and cache all entries from a reciter's detailed.json."""
    cached = cache.get_seg_cache(reciter)
    if cached is not None:
        return cached
    path = RECITATION_SEGMENTS_PATH / reciter / "detailed.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    if "_meta" in doc:
        cache.set_seg_meta(reciter, doc["_meta"])
    entries = doc.get("entries", [])
    cache.set_seg_cache(reciter, entries)
    # Fallback: if detailed.json had no _meta, try segments.json
    if not cache.get_seg_meta(reciter):
        seg_path = path.parent / "segments.json"
        if seg_path.exists():
            with open(seg_path, encoding="utf-8") as sf:
                try:
                    seg_doc = json.load(sf)
                    if "_meta" in seg_doc:
                        cache.set_seg_meta(reciter, seg_doc["_meta"])
                except json.JSONDecodeError:
                    pass
    return entries


def load_audio_urls(audio_source: str, reciter: str) -> dict:
    """Load verse/chapter URL map from data/audio/<audio_source>/<reciter>.json."""
    key = f"{audio_source}/{reciter}"
    cached = cache.get_audio_url_cache(key)
    if cached is not None:
        return cached
    path = AUDIO_METADATA_PATH / audio_source / f"{reciter}.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        urls = json.load(f)
    urls.pop("_meta", None)
    cache.set_audio_url_cache(key, urls)
    return urls


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
        with open(sip, encoding="utf-8") as f:
            si = json.load(f)
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
    with open(SURAH_INFO_PATH, encoding="utf-8") as f:
        raw = json.load(f)
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
    for category in ("by_surah", "by_ayah"):
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
                name = slug.replace("_", " ").title()
                reciters.append({"slug": slug, "name": name})
            if reciters:
                cat_data[source] = reciters
        if cat_data:
            result[category] = cat_data
    cache.set_audio_sources_cache(result)
    return result
