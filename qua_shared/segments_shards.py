"""Shared sharding logic for the deployed Aligner preload-mode read-path.

Splits a `detailed.json` document into per-chapter `.json.gz` shards the
aligner Space's preload UI fetches on demand. Used by:

  - `scripts/release/build_reciter.py --build-segments <slug>` — uploads
    shards to the HF dataset for the deployed read path.

The aligner Space talks to the same HF dataset as the Inspector's Timestamps
tab, sharing one manifest. This module is the segments-side twin of
`qua_shared/timestamps_shards.py`.

Shard schema is documented in `C:\\Users\\ahmed\\.claude\\plans\\wondrous-hopping-mochi.md`
§1. Slim per-segment payload (`matched_ref`, `time_start`, `time_end`,
`confidence`) — `segment_uid` and `ignored_categories` are deliberately not
shipped because preload-mode UI does not render them.
"""

from __future__ import annotations

import gzip
import hashlib
from typing import Any

# Schema fields preserved from the source detailed.json `_meta` block. The
# aligner Space uses these for provenance / the audio prewarm path; everything
# else (pad migration trail, raw VAD knobs) is dropped to keep shards tight.
_PRESERVED_META_FIELDS = (
    "created_at",
    "asr_model",
    "vad_model",
    "audio_source",
    "pad_left_ms",
    "pad_right_ms",
)

SCHEMA_VERSION = 1


def _slim_segment(seg: dict) -> dict:
    """Strip an entry's segment dict down to the four preload-relevant fields.

    Order of keys is fixed so that orjson output is deterministic across runs
    (load-bearing for the manifest's `segments_shard_hashes` diff-skip).
    """
    return {
        "matched_ref": seg.get("matched_ref", ""),
        "time_start": seg.get("time_start", 0),
        "time_end": seg.get("time_end", 0),
        "confidence": float(seg.get("confidence") or 0.0),
    }


def split_to_shards(
    detailed_doc: dict,
    *,
    reciter: str,
    audio_category: str,
) -> dict[int, dict]:
    """Split a `detailed.json` into per-chapter shard documents.

    Args:
        detailed_doc: parsed `detailed.json` (top-level `_meta` plus an
            `entries` list of `{ref, audio, segments}` dicts).
        reciter: slug stamped into each shard's `_meta`.
        audio_category: ``"by_surah"`` or ``"by_ayah"`` — determines whether
            the shard carries a single ``audio_url`` (per-chapter file) or an
            ``audio_urls`` map keyed by verse_ref (per-ayah files).

    Returns:
        ``{chapter: shard_doc}`` mapping. Each shard_doc has a `_meta` block
        plus a ``segments`` list preserving alignment time order.
    """
    src_meta = detailed_doc.get("_meta", {}) or {}
    entries = detailed_doc.get("entries") or []

    # Group segments + audio URLs by chapter. For by_surah, one entry per
    # chapter, so audio_url is a single string. For by_ayah, multiple entries
    # share a chapter and each carries its own per-ayah URL.
    by_chapter_segments: dict[int, list[dict]] = {}
    by_chapter_audio_url: dict[int, str] = {}                # by_surah
    by_chapter_audio_urls_map: dict[int, dict[str, str]] = {}  # by_ayah

    for entry in entries:
        ref = entry.get("ref") or ""
        if not ref:
            continue
        try:
            chapter = int(ref.split(":", 1)[0])
        except ValueError:
            continue

        # Slim each segment in-place into the chapter bucket, preserving
        # the alignment's time order (entry["segments"] is already in order).
        bucket = by_chapter_segments.setdefault(chapter, [])
        for seg in entry.get("segments") or []:
            if not seg.get("matched_ref"):
                continue
            bucket.append(_slim_segment(seg))

        audio = entry.get("audio") or ""
        if not audio:
            continue
        if audio_category == "by_surah":
            # Multiple entries per chapter shouldn't happen for by_surah, but
            # if they do, last-write wins (mirrors detailed.json's first-match
            # lookup in the legacy preload path).
            by_chapter_audio_url[chapter] = audio
        else:  # by_ayah — key by the entry ref (e.g. "2:1")
            by_chapter_audio_urls_map.setdefault(chapter, {})[ref] = audio

    # Build each shard with its own `_meta`.
    out: dict[int, dict] = {}
    for chapter, segments in by_chapter_segments.items():
        meta: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "reciter": reciter,
            "chapter": chapter,
            "audio_category": audio_category,
        }
        if audio_category == "by_surah":
            audio_url = by_chapter_audio_url.get(chapter, "")
            if audio_url:
                meta["audio_url"] = audio_url
        else:
            urls_map = by_chapter_audio_urls_map.get(chapter, {})
            if urls_map:
                # Sort keys for deterministic byte-output → stable hashes.
                meta["audio_urls"] = {
                    k: urls_map[k] for k in sorted(urls_map.keys(), key=_verse_key_sort)
                }

        # Preserve aligner-side meta fields when present.
        for field in _PRESERVED_META_FIELDS:
            if field in src_meta:
                meta[field] = src_meta[field]

        out[chapter] = {"_meta": meta, "segments": segments}

    return out


def _verse_key_sort(key: str) -> tuple[int, int, int]:
    """Sort key for verse refs. Compound refs sort by their start tuple.

    Twin of timestamps_shards._verse_key_sort — kept local so this module has
    no cross-script dependency.
    """
    first = key.split("-", 1)[0]
    parts = first.split(":")
    try:
        return (
            int(parts[0]) if len(parts) > 0 else 0,
            int(parts[1]) if len(parts) > 1 else 0,
            int(parts[2]) if len(parts) > 2 else 0,
        )
    except ValueError:
        return (0, 0, 0)


def gzip_shard(shard_doc: dict) -> bytes:
    """Serialize and gzip a shard document deterministically.

    Uses orjson for speed/UTF-8 fidelity. `mtime=0` on the gzip header so
    re-running the build with unchanged input produces byte-identical output
    (load-bearing for the hash-diff cache).
    """
    import orjson

    payload = orjson.dumps(shard_doc)
    return gzip.compress(payload, compresslevel=6, mtime=0)


def sha256_hex(b: bytes) -> str:
    """SHA-256 hex digest of `b`. Used by the manifest's
    `segments_shard_hashes` index."""
    return hashlib.sha256(b).hexdigest()
