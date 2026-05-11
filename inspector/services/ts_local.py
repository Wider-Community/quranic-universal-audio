"""Timestamp manifest + per-chapter shard server.

Two read modes share one frontend protocol:

- **local**  — slices ``data/timestamps/by_*/*/timestamps_full.json`` on demand
  via ``scripts.lib.timestamps_shards`` and gzips the per-chapter result.
- **bucket** — reads ``<bucket>/published/<slug>/timestamps/<chapter>.json``
  on demand and gzips per request (small per-reciter LRU). Manifest is
  composed from the bucket catalog + state + audio_manifest sidecars.

Mode is picked by ``config.TS_SOURCE`` once at import; ``invalidate()`` drops
the cache so tests / future hot-reload can re-pick.
"""

from __future__ import annotations

import gzip
import json
import logging
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import (
    AUDIO_METADATA_PATH,
    DK_SCRIPT_PATH,
    QPC_HAFS_PATH,
    TIMESTAMPS_PATH,
    TS_SOURCE,
)
from constants import TS_AUDIO_CATEGORIES
from scripts.lib.timestamps_shards import (
    SCHEMA_VERSION,
    derive_url_template,
    gzip_shard,
    split_to_shards,
)
from services import data_dir
from services import catalog as catalog_service
from services import state as state_service
from services.audio_meta import vbr_chapters_for_reciter
from services.hf_bucket import StorageNotFound, get_backend
from services import storage_paths
from utils.formatting import slug_to_name

log = logging.getLogger("inspector")

# Resource keys served at /api/ts/resource/<key>. The OTF font is bundled
# with the SPA (frontend/public/fonts/) and intentionally absent here.
_RESOURCE_KEYS = ("qpc_hafs", "digital_khatt")
_RESOURCE_PATHS = {
    "qpc_hafs": QPC_HAFS_PATH,
    "digital_khatt": DK_SCRIPT_PATH,
}

# Lazy-built caches. Single lock guards the build path; reads are dict
# lookups so we don't need to hold the lock past `_ensure_built()`.
_lock = threading.Lock()
_built = False
_manifest_bytes: bytes | None = None
_shard_bytes: dict[tuple[str, int], bytes] = {}
_resource_bytes: dict[str, bytes] = {}


def _walk_local_reciters() -> list[tuple[str, str]]:
    """Return ``[(slug, audio_category), ...]`` for every reciter under
    `data/timestamps/by_*_audio/`.

    A slug present in both `by_ayah_audio` and `by_surah_audio` reports
    the by_surah row (matching the HF manifest's preference rule).
    """
    seen: dict[str, str] = {}
    if not TIMESTAMPS_PATH.exists():
        return []
    for category in TS_AUDIO_CATEGORIES:
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
            # Prefer by_surah_audio when both exist (matches build_reciter's rule).
            existing = seen.get(slug)
            if existing is None or category == "by_surah_audio":
                seen[slug] = category
    return sorted(seen.items())


def _find_audio_manifest(slug: str) -> dict | None:
    """Locate `data/audio/<category>/<source>/<slug>.json` and parse it."""
    if not AUDIO_METADATA_PATH.exists():
        return None
    for category in ("by_surah", "by_ayah"):
        cat_dir = AUDIO_METADATA_PATH / category
        if not cat_dir.is_dir():
            continue
        for source_dir in cat_dir.iterdir():
            if not source_dir.is_dir():
                continue
            path = source_dir / f"{slug}.json"
            if path.exists():
                try:
                    return json.loads(path.read_bytes())
                except (json.JSONDecodeError, OSError):
                    return None
    return None


def _load_ts_doc(slug: str, audio_category: str) -> dict | None:
    """Load the reciter's `timestamps_full.json` (or fallback `timestamps.json`)."""
    base = TIMESTAMPS_PATH / audio_category / slug
    for name in ("timestamps_full.json", "timestamps.json"):
        path = base / name
        if path.exists():
            try:
                return json.loads(path.read_bytes())
            except (json.JSONDecodeError, OSError):
                return None
    return None


def _build_reciter_block(
    slug: str, audio_category: str
) -> tuple[dict, dict[int, bytes]]:
    """Compose a manifest reciter block + the gzipped per-chapter shard bytes.

    Returns ``(reciter_block, {chapter: gzipped_shard_bytes})``. The shard
    bytes go straight into the on-demand serving cache; the reciter block
    is composed from the source `_meta` + audio manifest metadata.
    """
    doc = _load_ts_doc(slug, audio_category)
    if doc is None:
        return {}, {}

    audio_cat_short = audio_category.replace("_audio", "")
    audio_manifest = _find_audio_manifest(slug) or {}
    url_template = (
        derive_url_template(audio_manifest, audio_cat_short)
        if audio_manifest
        else ""
    )
    audio_manifest_meta = audio_manifest.get("_meta", {}) if audio_manifest else {}

    shards = split_to_shards(
        doc,
        reciter=slug,
        audio_category=audio_cat_short,
        url_template=url_template,
        audio_urls_fallback=audio_manifest if not url_template else None,
    )
    shard_bytes: dict[int, bytes] = {ch: gzip_shard(d) for ch, d in shards.items()}

    block: dict[str, Any] = {
        "name_en": audio_manifest_meta.get("name_en") or slug_to_name(slug),
        "name_ar": audio_manifest_meta.get("name_ar"),
        "riwayah": audio_manifest_meta.get("riwayah", "hafs_an_asim"),
        "style": audio_manifest_meta.get("style", "murattal"),
        "source": audio_manifest_meta.get("source", ""),
        "audio_category": audio_cat_short,
        "url_template": url_template,
        "ts_chapters": sorted(shards.keys()),
        "vbr_chapters": vbr_chapters_for_reciter(slug),
        # Validation falls through to /api/ts/validate/<slug> in local mode;
        # the manifest carries no pre-computed boundary_mismatches.
        "validation": {"boundary_mismatches": []},
    }
    return block, shard_bytes


def _build_manifest_dict(reciters_block: dict[str, dict]) -> dict:
    """Compose the manifest body. Mirrors the HF manifest schema."""
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": "",
        # Local-mode URLs join cleanly with relative resource/shard paths.
        "dataset_base_url": "",
        "shard_url_template": "/api/ts/shard/{reciter}/{chapter}",
        "resources": {key: f"/api/ts/resource/{key}" for key in _RESOURCE_KEYS},
        "reciters": reciters_block,
    }


def _build_resource_bytes() -> dict[str, bytes]:
    """Gzip every advertised resource file. Missing files are skipped."""
    out: dict[str, bytes] = {}
    for key, path in _RESOURCE_PATHS.items():
        if not path.exists():
            continue
        out[key] = gzip.compress(path.read_bytes(), compresslevel=6, mtime=0)
    return out


def _ensure_built_local() -> None:
    """Local-mode: lazy boot — walk on-disk tree, eagerly build all shards.

    Idempotent and thread-safe. First request pays a one-time cost
    proportional to local reciter count; later are dict lookups.
    """
    global _built, _manifest_bytes
    reciters_block: dict[str, dict] = {}
    shards_acc: dict[tuple[str, int], bytes] = {}
    for slug, audio_category in _walk_local_reciters():
        block, shard_bytes = _build_reciter_block(slug, audio_category)
        if not block:
            continue
        reciters_block[slug] = block
        for chapter, body in shard_bytes.items():
            shards_acc[(slug, chapter)] = body

    manifest = _build_manifest_dict(reciters_block)
    _manifest_bytes = gzip.compress(
        json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
        compresslevel=6,
        mtime=0,
    )
    _shard_bytes.clear()
    _shard_bytes.update(shards_acc)
    _resource_bytes.clear()
    _resource_bytes.update(_build_resource_bytes())
    _built = True
    log.info(
        "ts_local: built local-mode manifest (%d reciters, %d shards, %d resources)",
        len(reciters_block),
        len(_shard_bytes),
        len(_resource_bytes),
    )


# ----------------------------------------------------------------------
# Bucket-mode builder
#
# Walks completed reciters in state, joins with catalog metadata, lists
# per-chapter timestamps in ``<bucket>/published/<slug>/timestamps/``, and
# composes a manifest with the same wire shape as local mode. Shard bytes
# are read on demand and held in a per-process LRU (~256 entries ≈ 1–4 MB
# of gzipped JSON) — full eager prebuild was rejected because cold boot on
# free CPU-basic shouldn't pay 600+ bucket reads up front.
# ----------------------------------------------------------------------

_SHARD_LRU_CAP = 256
_shard_lru: "OrderedDict[tuple[str, int], bytes]" = OrderedDict()


def _bucket_completed_reciters() -> list[str]:
    """Return slugs of reciters that have published timestamps in the bucket.

    Source: state file (released/completed states). Filtered by presence of
    at least one timestamps file. Empty when the state file is empty (e.g.
    fresh bucket).
    """
    out: list[str] = []
    for row in state_service.all_rows():
        if row.state.value not in ("released", "completed"):
            continue
        chapters = data_dir.list_published_timestamps_chapters(row.slug)
        if chapters:
            out.append(row.slug)
    return out


def _bucket_url_template(slug: str, audio_category: str) -> str:
    """Resolve the audio URL template from the bucket audio_manifest sidecar.

    Returns ``""`` if the sidecar is absent or the template can't be derived;
    callers tolerate empty templates (audio playback simply won't have a URL
    pattern, but the rest of the TS UI works).
    """
    try:
        raw = get_backend().read_json(storage_paths.audio_manifest_path(slug))
    except StorageNotFound:
        return ""
    if not isinstance(raw, dict):
        return ""
    return derive_url_template(raw, audio_category) or ""


def _bucket_reciter_block(slug: str, ts_chapters: list[int]) -> dict | None:
    """Compose a manifest reciter block for a bucket-mode reciter.

    Joins the catalog (display + delivery metadata) with the audio_manifest
    sidecar (URL template) and the precomputed VBR chapter list. Returns
    ``None`` when the catalog has no delivery for ``slug`` (defensive — every
    state row should have a catalog entry once cutover seeding is finished).
    """
    catalog = catalog_service.snapshot()
    delivery = next((d for d in catalog.deliveries if d.slug == slug), None)
    reciter = (
        catalog.find_reciter(delivery.reciter_id) if delivery is not None else None
    )

    name_en = reciter.name_en if reciter is not None else slug_to_name(slug)
    name_ar = reciter.name_ar if reciter is not None else None
    riwayah = delivery.riwayah if delivery is not None else "hafs_an_asim"
    style = delivery.style if delivery is not None else "murattal"
    source = delivery.source if delivery is not None else ""
    audio_category = (
        delivery.audio_category.value if delivery is not None else "by_surah"
    )

    return {
        "name_en": name_en,
        "name_ar": name_ar,
        "riwayah": riwayah,
        "style": style,
        "source": source,
        "audio_category": audio_category,
        "url_template": _bucket_url_template(slug, audio_category),
        "ts_chapters": ts_chapters,
        "vbr_chapters": vbr_chapters_for_reciter(slug),
        "validation": {"boundary_mismatches": []},
    }


def _ensure_built_bucket() -> None:
    """Bucket-mode: build manifest from state + catalog + bucket file listing.

    Shards are NOT eagerly loaded — see ``_load_bucket_shard()``.
    """
    global _built, _manifest_bytes
    reciters_block: dict[str, dict] = {}
    for slug in _bucket_completed_reciters():
        chapters = data_dir.list_published_timestamps_chapters(slug)
        if not chapters:
            continue
        block = _bucket_reciter_block(slug, chapters)
        if block is not None:
            reciters_block[slug] = block

    manifest = _build_manifest_dict(reciters_block)
    _manifest_bytes = gzip.compress(
        json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
        compresslevel=6,
        mtime=0,
    )
    _shard_bytes.clear()
    _shard_lru.clear()
    _resource_bytes.clear()
    _resource_bytes.update(_build_resource_bytes())
    _built = True
    log.info(
        "ts_local: built bucket-mode manifest (%d reciters, %d resources)",
        len(reciters_block),
        len(_resource_bytes),
    )


def _load_bucket_shard(reciter: str, chapter: int) -> bytes | None:
    """Read + gzip a single per-chapter timestamps file from the bucket.

    LRU-cached so chapter scrubbing within one reciter doesn't repeatedly
    pay the bucket fetch + gzip cost.
    """
    key = (reciter, chapter)
    cached = _shard_lru.get(key)
    if cached is not None:
        _shard_lru.move_to_end(key)
        return cached
    raw = data_dir.read_timestamps_chapter(reciter, chapter)
    if raw is None:
        return None
    body = gzip.compress(raw, compresslevel=6, mtime=0)
    _shard_lru[key] = body
    _shard_lru.move_to_end(key)
    while len(_shard_lru) > _SHARD_LRU_CAP:
        _shard_lru.popitem(last=False)
    return body


# ----------------------------------------------------------------------
# Public API — dispatches on TS_SOURCE
# ----------------------------------------------------------------------


def _ensure_built() -> None:
    """Mode-aware lazy boot. Idempotent and thread-safe."""
    if _built:
        return
    with _lock:
        if _built:
            return
        if TS_SOURCE == "bucket":
            _ensure_built_bucket()
        else:
            _ensure_built_local()


def manifest_bytes() -> bytes:
    _ensure_built()
    assert _manifest_bytes is not None
    return _manifest_bytes


def shard_bytes(reciter: str, chapter: int) -> bytes | None:
    _ensure_built()
    if TS_SOURCE == "bucket":
        return _load_bucket_shard(reciter, chapter)
    return _shard_bytes.get((reciter, chapter))


def resource_bytes(name: str) -> bytes | None:
    _ensure_built()
    return _resource_bytes.get(name)


def invalidate() -> None:
    """Drop the cached manifest + shards. Tests / future hot-reload hook."""
    global _built, _manifest_bytes
    with _lock:
        _built = False
        _manifest_bytes = None
        _shard_bytes.clear()
        _shard_lru.clear()
        _resource_bytes.clear()
