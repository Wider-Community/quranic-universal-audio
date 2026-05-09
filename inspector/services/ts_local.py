"""Local-mode timestamp manifest + per-chapter shard server.

In local mode the frontend uses the same shard-fetch model it uses against
the HF dataset. This module slices `data/timestamps/by_*/*/timestamps_full.json`
on demand, gzips the per-chapter result, and composes a manifest the
frontend can read with the same parser path as the HF manifest.

Flow:
  1. First request to /api/ts/manifest walks the local timestamps tree
     and lazy-loads each reciter's timestamps_full.json once.
  2. `split_to_shards()` produces per-chapter docs; each is gzipped and
     cached keyed `(reciter, chapter)` so subsequent shard fetches are
     a dict lookup + Flask response build.
  3. The composed manifest mirrors the HF manifest schema as closely as
     possible — same `dataset_base_url`/`shard_url_template`/`resources`
     skeleton — but populated with local-mode URLs and without the
     pre-computed `validation.boundary_mismatches` (the validation panel
     falls through to /api/ts/validate/<slug> in local mode).
"""

from __future__ import annotations

import gzip
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import (
    AUDIO_METADATA_PATH,
    DK_SCRIPT_PATH,
    QPC_HAFS_PATH,
    TIMESTAMPS_PATH,
)
from constants import TS_AUDIO_CATEGORIES
from scripts.lib.timestamps_shards import (
    SCHEMA_VERSION,
    derive_url_template,
    gzip_shard,
    split_to_shards,
)
from services.audio_meta import vbr_chapters_for_reciter
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


def _ensure_built() -> None:
    """Lazy boot: walk the timestamps tree, build all shards + manifest.

    Idempotent and thread-safe. The first shard or manifest request pays
    a one-time cost proportional to the number of local reciters; later
    requests are dict lookups.
    """
    global _built, _manifest_bytes
    if _built:
        return
    with _lock:
        if _built:
            return
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
            "ts_local: built manifest (%d reciters, %d shards, %d resources)",
            len(reciters_block),
            len(_shard_bytes),
            len(_resource_bytes),
        )


def manifest_bytes() -> bytes:
    _ensure_built()
    assert _manifest_bytes is not None
    return _manifest_bytes


def shard_bytes(reciter: str, chapter: int) -> bytes | None:
    _ensure_built()
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
        _resource_bytes.clear()
