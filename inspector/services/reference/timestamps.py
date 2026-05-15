"""Timestamp manifest + per-chapter shard server.

Bucket-only: manifest is composed from state (released/completed reciters)
+ catalog (display + delivery metadata) + audio_manifest sidecars (URL
template). Per-chapter shards read from
``<bucket>/published/<slug>/timestamps/<chapter>.json`` on demand and gzip
through a small per-process LRU so chapter scrubbing within one reciter
doesn't pay the bucket fetch + gzip cost on every shard hit.

``invalidate()`` drops the cache for tests / future hot-reload.
"""

from __future__ import annotations

import gzip
import json
import logging
import threading
from collections import OrderedDict
from datetime import datetime, timezone

from config import DK_SCRIPT_PATH, QPC_HAFS_PATH
from scripts.lib.timestamps_shards import SCHEMA_VERSION, derive_url_template
from services.storage import data_dir
from services.state import catalog as catalog_service
from services.state import state as state_service
from services.audio.audio_meta import vbr_chapters_for_reciter
from services.storage.hf_bucket import StorageNotFound, get_backend
from services.storage import storage_paths
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
_resource_bytes: dict[str, bytes] = {}

_SHARD_LRU_CAP = 256
_shard_lru: "OrderedDict[tuple[str, int], bytes]" = OrderedDict()


def _build_manifest_dict(reciters_block: dict[str, dict]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": "",
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


def _bucket_completed_reciters() -> list[str]:
    """Return slugs of reciters that have published timestamps in the bucket."""
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

    The v2 sidecar shape is ``{schema_version, slug, _meta, chapters: {ch: {url, ...}}}``.
    ``derive_url_template`` expects a flat ``{chapter: url}`` dict so flatten
    before calling. Returns ``""`` when the sidecar is absent or the template
    can't be derived — callers degrade gracefully (no audio playback URL).
    """
    try:
        raw = get_backend().read_json(storage_paths.audio_manifest_path(slug))
    except StorageNotFound:
        log.warning("timestamps: audio_manifest sidecar missing for %s", slug)
        return ""
    if not isinstance(raw, dict):
        log.warning(
            "timestamps: audio_manifest sidecar for %s is not a dict (got %s)",
            slug, type(raw).__name__,
        )
        return ""
    chapters = raw.get("chapters")
    if not isinstance(chapters, dict):
        log.warning(
            "timestamps: audio_manifest sidecar for %s missing 'chapters' map "
            "(top-level keys: %s)",
            slug, list(raw.keys())[:8],
        )
        return ""
    flat: dict[str, str] = {}
    for k, v in chapters.items():
        if isinstance(v, dict) and isinstance(v.get("url"), str):
            flat[str(k)] = v["url"]
    if not flat:
        log.warning("timestamps: no chapter URLs derivable from sidecar for %s", slug)
        return ""
    template = derive_url_template(flat, audio_category) or ""
    if not template:
        log.warning(
            "timestamps: derive_url_template returned empty for %s (audio_cat=%s, "
            "chapter_count=%d)", slug, audio_category, len(flat),
        )
    return template


def _bucket_reciter_block(slug: str, ts_chapters: list[int]) -> dict | None:
    """Compose a manifest reciter block for a bucket-mode reciter.

    Joins the catalog (display + delivery metadata) with the audio_manifest
    sidecar (URL template) and the precomputed VBR chapter list. Falls back
    to slug-derived defaults when the catalog has no delivery for ``slug``.
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


def _ensure_built() -> None:
    """Lazy boot — build manifest from state + catalog + bucket listing.

    Idempotent and thread-safe. Shards are NOT eagerly loaded — see
    ``_load_bucket_shard()``.
    """
    global _built, _manifest_bytes
    if _built:
        return
    with _lock:
        if _built:
            return
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
        _shard_lru.clear()
        _resource_bytes.clear()
        _resource_bytes.update(_build_resource_bytes())
        _built = True
        log.info(
            "timestamps: built manifest (%d reciters, %d resources)",
            len(reciters_block),
            len(_resource_bytes),
        )


def _load_bucket_shard(reciter: str, chapter: int) -> bytes | None:
    """Read + gzip a per-chapter timestamps file from the bucket.

    LRU-cached so chapter scrubbing within one reciter doesn't pay the
    bucket fetch + gzip cost on every shard hit.
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


def manifest_bytes() -> bytes:
    _ensure_built()
    assert _manifest_bytes is not None
    return _manifest_bytes


def shard_bytes(reciter: str, chapter: int) -> bytes | None:
    _ensure_built()
    return _load_bucket_shard(reciter, chapter)


def resource_bytes(name: str) -> bytes | None:
    _ensure_built()
    return _resource_bytes.get(name)


def invalidate() -> None:
    """Drop the cached manifest + shards. Tests / future hot-reload hook."""
    global _built, _manifest_bytes
    with _lock:
        _built = False
        _manifest_bytes = None
        _shard_lru.clear()
        _resource_bytes.clear()
