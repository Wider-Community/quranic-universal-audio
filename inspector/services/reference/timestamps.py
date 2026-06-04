"""Timestamp manifest + per-chapter shard server.

Bucket-only: manifest is composed from state (released reciters)
+ catalog (display + delivery metadata) + audio_manifest sidecars (URL
template). Per-chapter shards are read as raw gzip from
``<bucket>/reciters/<slug>/timestamps/<chapter>.json.gz`` on demand — the
bucket gz body is the wire body (segment-array shape), so serving is a byte
pass-through cached through a small per-process LRU so chapter scrubbing
within one reciter doesn't re-pay the bucket fetch.

``invalidate()`` drops the cache for tests / future hot-reload.
"""

from __future__ import annotations

import gzip
import json
import logging
import threading
from collections import OrderedDict
from datetime import UTC, datetime

from config import DK_SCRIPT_PATH
from qua_shared.schemas import ReciterCatalog
from qua_shared.timestamps_shards import SCHEMA_VERSION, derive_url_template
from services.audio.audio_meta import chapter_numbers, chapter_urls, vbr_chapters_for_reciter
from services.state import catalog as catalog_service
from services.state import state as state_service
from services.storage import data_dir, static_refs
from utils.formatting import slug_to_name

log = logging.getLogger("inspector")

# Resource keys served at /api/ts/resource/<key>. The OTF font is bundled
# with the SPA (frontend/public/fonts/) and intentionally absent here.
_RESOURCE_KEYS = ("qpc_hafs", "digital_khatt")

# Lazy-built caches. Single lock guards the build path; reads are dict
# lookups so we don't need to hold the lock past `_ensure_built()`.
_lock = threading.Lock()
_built = False
# The ``db_seq`` the cache was built at. The manifest is a projection of which
# slugs are ``released`` (+ catalog/sidecar metadata), so it MUST rebuild
# whenever the committed DB advances. Keying on ``db_seq`` (mirrors
# ``catalog.snapshot()``) makes the cache self-healing: any in-process state
# commit bumps ``db_seq``, so the next manifest request rebuilds — no reliance
# on the explicit post-commit ``invalidate()`` (which sits after the durable
# upload in ``state.transition`` and is skipped if that step raises). ``None``
# forces a rebuild (boot / explicit invalidate).
_built_seq: int | None = None
_manifest_bytes: bytes | None = None
_resource_bytes: dict[str, bytes] = {}
# Slugs the manifest advertises (released + chapter-derivable). The shard route
# gates on this so a guessed ``/shard/<slug>/<ch>`` URL can't serve a
# non-released reciter's timestamps — the unified ``reciters/`` prefix no longer
# isolates WIP timestamps by folder, so the released invariant is enforced here.
_served_slugs: set[str] = set()

_SHARD_LRU_CAP = 256
_shard_lru: OrderedDict[tuple[str, int], bytes] = OrderedDict()


def _build_manifest_dict(reciters_block: dict[str, dict]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": "",
        "dataset_base_url": "",
        "shard_url_template": "/api/ts/shard/{reciter}/{chapter}",
        "resources": {key: f"/api/ts/resource/{key}" for key in _RESOURCE_KEYS},
        "reciters": reciters_block,
    }


def _build_resource_bytes() -> dict[str, bytes]:
    """Gzip every advertised resource for ``/api/ts/resource/<key>``.

    ``qpc_hafs`` resolves via ``static_refs.load_qpc_bytes`` (local image →
    bucket — the deployed Space's image ``.gz`` is an LFS pointer, so real
    bytes come from the bucket). ``digital_khatt`` ships uncompressed in the
    image and reads directly (HF auto-LFS is keyed on extension, so the
    ~10 MB ``*.json`` is exempt). A missing/unavailable resource is skipped,
    never raised — the manifest must not 500 on a degraded resource."""
    out: dict[str, bytes] = {}
    qpc = static_refs.load_qpc_bytes()
    if qpc:
        out["qpc_hafs"] = gzip.compress(qpc, compresslevel=6, mtime=0)
    if DK_SCRIPT_PATH.exists():
        out["digital_khatt"] = gzip.compress(DK_SCRIPT_PATH.read_bytes(), compresslevel=6, mtime=0)
    return out


def _published_reciter_slugs() -> list[str]:
    """Return slugs of reciters in the ``released`` lifecycle state.

    State alone — no bucket I/O. The lifecycle gate
    ``under_review → released`` (publish fires only on timestamps-job success)
    is what guarantees these slugs have timestamps published; we don't re-verify
    by walking the bucket dir.
    """
    return [row.slug for row in state_service.all_rows() if row.state.value == "released"]


def _ts_chapters_for(slug: str, delivery) -> list[int]:
    """Resolve the chapter list the manifest advertises for ``slug``.

    For a fully-documented complete by_surah mushaf (``delivery.chapter_count ==
    114``) derive ``1..114`` from the catalog (DB) — robust to a sidecar whose
    chapter keys are partial/corrupt, and provably contiguous so no advertised
    chapter can 404 (the released gate guarantees all 114 shards exist).
    Everything else (partial reciters, by_ayah, no delivery) falls back to the
    gap-accurate sidecar keys.

    NOTE: ``url_template`` + ``vbr_chapters`` still come from the sidecar (see
    ``_bucket_reciter_block``), so this hardens the chapter list but does not yet
    avoid the per-slug sidecar read — moving those two fields into the catalog is
    the follow-up that would let the manifest build skip the bucket entirely.
    """
    if (
        delivery is not None
        and getattr(delivery.audio_category, "value", delivery.audio_category) == "by_surah"
        and delivery.chapter_count == 114
    ):
        return list(range(1, 115))
    return chapter_numbers(slug)


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
            "chapter_count=%d)",
            slug,
            audio_category,
            len(flat),
        )
    return template


def _bucket_reciter_block(
    slug: str,
    ts_chapters: list[int],
    catalog: ReciterCatalog,
    delivery=None,
) -> dict | None:
    """Compose a manifest reciter block for a bucket-mode reciter.

    Joins the catalog (display + delivery metadata) with the audio_manifest
    sidecar (URL template) and the precomputed VBR chapter list. Falls back
    to slug-derived defaults when the catalog has no delivery for ``slug``.

    The caller passes one shared ``catalog`` snapshot so the manifest build
    doesn't re-snapshot (deep-copy) per reciter inside ``_ensure_built``, and
    the pre-resolved ``delivery`` so we don't re-``find_delivery`` it here.
    """
    if delivery is None:
        delivery = catalog.find_delivery(slug)
    reciter = catalog.find_reciter(delivery.reciter_id) if delivery is not None else None

    name_en = reciter.name_en if reciter is not None else slug_to_name(slug)
    name_ar = reciter.name_ar if reciter is not None else None
    riwayah = delivery.riwayah if delivery is not None else "hafs_an_asim"
    style = delivery.style if delivery is not None else "murattal"
    source = delivery.source if delivery is not None else ""
    audio_category = delivery.audio_category.value if delivery is not None else "by_surah"

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
    global _built, _built_seq, _manifest_bytes, _served_slugs
    # Lazy import (keeps this module light, like catalog.snapshot()'s db import).
    from services import db as _db

    seq = _db.current_db_seq()
    if _built and _built_seq == seq:
        return
    with _lock:
        # Re-check inside the lock; another thread may have just rebuilt at seq.
        if _built and _built_seq == seq:
            return
        catalog = catalog_service.snapshot()
        reciters_block: dict[str, dict] = {}
        for slug in _published_reciter_slugs():
            delivery = catalog.find_delivery(slug)
            chapters = _ts_chapters_for(slug, delivery)
            if not chapters:
                # No catalog-derivable chapters AND no audio_manifest sidecar
                # (or unparseable keys) — skip rather than emit an empty chapter
                # list the FE can't render. Surfaces as "missing from dropdown".
                log.warning(
                    "timestamps: skipping %s — no chapter numbers derivable "
                    "from catalog or audio_manifest sidecar",
                    slug,
                )
                continue
            block = _bucket_reciter_block(slug, chapters, catalog, delivery)
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
        _built_seq = seq
        log.info(
            "timestamps: built manifest (%d reciters, %d resources)",
            len(reciters_block),
            len(_resource_bytes),
        )


def _load_bucket_shard(reciter: str, chapter: int) -> bytes | None:
    """Return the raw gzipped per-chapter shard from the bucket, or ``None``.

    The bucket gz body IS the wire body (segment-array shape, slim ``_meta``) —
    the read path is a byte pass-through, no inflate/reshape/recompress. LRU
    so chapter scrubbing within one reciter doesn't re-pay the bucket fetch.
    """
    key = (reciter, chapter)
    cached = _shard_lru.get(key)
    if cached is not None:
        _shard_lru.move_to_end(key)
        return cached
    body = data_dir.read_timestamps_chapter_gz(reciter, chapter)
    if body is None:
        return None
    _shard_lru[key] = body
    _shard_lru.move_to_end(key)
    while len(_shard_lru) > _SHARD_LRU_CAP:
        _shard_lru.popitem(last=False)
    return body


def manifest_bytes() -> bytes:
    _ensure_built()
    assert _manifest_bytes is not None
    return _manifest_bytes


def shard_bytes(
    reciter: str,
    chapter: int,
    allow_unreleased: bool = False,
) -> bytes | None:
    _ensure_built()
    # Only serve shards for reciters the manifest advertises (released + has
    # chapters). Folder-level isolation is gone post-unification, so enforce the
    # released gate here too — don't leak a non-released reciter's timestamps.
    # ``allow_unreleased`` is the owner-preview bypass: the route sets it when
    # the caller holds ``timestamps.view_unreleased`` (capability check lives in
    # the route — this service stays Flask-free), letting an owner read a
    # generated-but-unreleased reciter's shards.
    if reciter not in _served_slugs and not allow_unreleased:
        return None
    return _load_bucket_shard(reciter, chapter)


def ts_validation_doc(
    reciter: str,
    allow_unreleased: bool = False,
) -> dict | None:
    """Verse-level ``ts_validation.json`` for a reciter, or ``None``.

    Same released/owner-preview gate as ``shard_bytes`` (capability check lives
    in the route). Returns ``None`` when the reciter isn't viewable or the
    sidecar is absent (reciter was never run with probe beams). Not cached:
    owner-preview-only traffic, and the file is re-written whenever a job
    re-runs — reading the small doc directly avoids a stale cache.
    """
    _ensure_built()
    if reciter not in _served_slugs and not allow_unreleased:
        return None  # not viewable → route returns 404
    # Viewable but never run with probe beams → empty doc (not a 404) so the
    # FE can render an empty panel.
    return data_dir.read_ts_validation_doc(reciter) or {"_meta": {}, "verses": {}}


def resource_bytes(name: str) -> bytes | None:
    _ensure_built()
    return _resource_bytes.get(name)


def invalidate() -> None:
    """Drop the cached manifest + shards.

    The ``db_seq`` check in ``_ensure_built`` is the authoritative rebuild
    trigger; this explicit drop is retained for tests and as a belt-and-braces
    hook (``state.transition`` still calls it post-commit). Also clears the
    audio-manifest sidecar caches the manifest build derives URLs from, so a
    re-extracted reciter's stale sidecar can't leak old URLs into the rebuild.
    """
    global _built, _built_seq, _manifest_bytes
    with _lock:
        _built = False
        _built_seq = None
        _manifest_bytes = None
        _shard_lru.clear()
        _resource_bytes.clear()
    # Outside the lock — different module's cache, no ordering dependency.
    from services.storage import cache as _cache

    _cache.invalidate_audio_manifest_cache()
