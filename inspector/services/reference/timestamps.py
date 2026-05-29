"""Timestamp manifest + per-chapter shard server.

Bucket-only: manifest is composed from state (released reciters)
+ catalog (display + delivery metadata) + audio_manifest sidecars (URL
template). Per-chapter shards read from
``<bucket>/reciters/<slug>/timestamps/<chapter>.json`` on demand and gzip
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
from scripts.lib.schemas import ReciterCatalog
from scripts.lib.timestamps_shards import SCHEMA_VERSION, derive_url_template
from scripts.lib.timestamps_dedup import is_v2, project_chapter_shard
from services.storage import data_dir
from services.state import catalog as catalog_service
from services.state import state as state_service
from services.audio.audio_meta import chapter_numbers, chapter_urls, vbr_chapters_for_reciter
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
# Slugs the manifest advertises (released + chapter-derivable). The shard route
# gates on this so a guessed ``/shard/<slug>/<ch>`` URL can't serve a
# non-released reciter's timestamps — the unified ``reciters/`` prefix no longer
# isolates WIP timestamps by folder, so the released invariant is enforced here.
_served_slugs: set[str] = set()

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


def _published_reciter_slugs() -> list[str]:
    """Return slugs of reciters in the ``released`` lifecycle state.

    State alone — no bucket I/O. The lifecycle gate
    ``awaiting_timestamps → released`` is what guarantees these slugs have
    timestamps published; we don't re-verify by walking the bucket dir.
    """
    return [
        row.slug
        for row in state_service.all_rows()
        if row.state.value == "released"
    ]


def _url_template(slug: str, audio_category: str) -> str:
    """Resolve the audio URL template from the in-memory audio_manifest sidecar cache.

    ``audio_meta.chapter_urls`` reads through ``_SIDECAR_CACHE`` — first hit
    per slug pays the bucket read, subsequent hits are dict lookups. Returns
    ``""`` when the sidecar is absent or the template can't be derived —
    callers degrade gracefully (no audio playback URL).
    """
    flat = chapter_urls(slug)
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


def _bucket_reciter_block(
    slug: str,
    ts_chapters: list[int],
    catalog: ReciterCatalog,
) -> dict | None:
    """Compose a manifest reciter block for a bucket-mode reciter.

    Joins the catalog (display + delivery metadata) with the audio_manifest
    sidecar (URL template) and the precomputed VBR chapter list. Falls back
    to slug-derived defaults when the catalog has no delivery for ``slug``.

    The caller passes one shared ``catalog`` snapshot so the manifest build
    doesn't re-snapshot (deep-copy) per reciter inside ``_ensure_built``.
    """
    delivery = catalog.find_delivery(slug)
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
        "url_template": _url_template(slug, audio_category),
        "ts_chapters": ts_chapters,
        "vbr_chapters": vbr_chapters_for_reciter(slug),
    }


def _ensure_built() -> None:
    """Lazy boot — build manifest from state + catalog + bucket listing.

    Idempotent and thread-safe. Shards are NOT eagerly loaded — see
    ``_load_bucket_shard()``.
    """
    global _built, _manifest_bytes, _served_slugs
    if _built:
        return
    with _lock:
        if _built:
            return
        catalog = catalog_service.snapshot()
        reciters_block: dict[str, dict] = {}
        for slug in _published_reciter_slugs():
            chapters = chapter_numbers(slug)
            if not chapters:
                # No audio_manifest sidecar (or unparseable keys) — skip the
                # reciter rather than emit a block with an empty chapter list
                # the FE can't render. Surfaces as "missing from dropdown",
                # same shape as the pre-fix bucket-empty case.
                log.warning(
                    "timestamps: skipping %s — no chapter numbers derivable "
                    "from audio_manifest sidecar", slug,
                )
                continue
            block = _bucket_reciter_block(slug, chapters, catalog)
            if block is not None:
                reciters_block[slug] = block

        _served_slugs = set(reciters_block)
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


def _shard_payload(raw: bytes, full: bool) -> bytes:
    """Return the gzipped shard body to serve.

    v1 shards (verse-map) pass through byte-identical — the entire current
    bucket is v1, so this is a no-op for existing data. v2 shards
    (occurrence lists) are deduped to the historical verse-map shape at read
    time via ``project_chapter_shard``; ``full=True`` serves every occurrence
    (owner preview / aligner "show all").
    """
    try:
        doc = json.loads(raw)
    except (ValueError, TypeError):
        doc = None
    if isinstance(doc, dict) and is_v2(doc):
        served = project_chapter_shard(doc, full=full)
        raw = json.dumps(served, ensure_ascii=False).encode("utf-8")
    return gzip.compress(raw, compresslevel=6, mtime=0)


def _load_bucket_shard(reciter: str, chapter: int, full: bool = False) -> bytes | None:
    """Read + gzip a per-chapter timestamps file from the bucket.

    LRU-cached (keyed on the ``full`` view too) so chapter scrubbing within
    one reciter doesn't pay the bucket fetch + gzip cost on every hit. v2
    shards are deduped at read time — see ``_shard_payload``.
    """
    key = (reciter, chapter, full)
    cached = _shard_lru.get(key)
    if cached is not None:
        _shard_lru.move_to_end(key)
        return cached
    raw = data_dir.read_timestamps_chapter(reciter, chapter)
    if raw is None:
        return None
    body = _shard_payload(raw, full)
    _shard_lru[key] = body
    _shard_lru.move_to_end(key)
    while len(_shard_lru) > _SHARD_LRU_CAP:
        _shard_lru.popitem(last=False)
    return body


def manifest_bytes() -> bytes:
    _ensure_built()
    assert _manifest_bytes is not None
    return _manifest_bytes


def shard_bytes(reciter: str, chapter: int, full: bool = False) -> bytes | None:
    _ensure_built()
    # Only serve shards for reciters the manifest advertises (released + has
    # chapters). Folder-level isolation is gone post-unification, so enforce the
    # released gate here too — don't leak a non-released reciter's timestamps.
    # (Owner preview of under-review reciters lands with the
    # ``timestamps.view_unreleased`` capability — separate increment.)
    if reciter not in _served_slugs:
        return None
    return _load_bucket_shard(reciter, chapter, full)


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
