"""Shared sharding logic for the deployed Timestamps tab read-path.

Two shard shapes share the deterministic gzip writer here:

  - `split_to_shards` — verse-keyed occurrence-list shards (the historical
    read-path shape produced from a `timestamps_full.json` document).
  - `build_segment_shards` — the temporal segment-array shape: each chapter
    is a flat `segments[]` array in recitation order with single-verse
    `ref`s and a slim `_meta`. This is the consumer-shaped bucket artifact
    (read path is a byte pass-through). See
    `docs/planning/ts-segment-array-migration.md`.

Phone tuples are ``[phone, start_ms, end_ms]``, optionally extended to
``[phone, start, end, geminate_start, geminate_end, bridge_rule]`` — slot 5
carries the cross-word tajweed bridge rule (see
`qua_sdk.components.timing.lib.cells`), stamped at write time by the pipeline.
Schema version 3 = bridge-tagged.

Both are gzipped via `gzip_shard` (level 6, mtime 0 → byte-stable output).
"""

from __future__ import annotations

import gzip
import hashlib
from typing import Any

# Schema fields preserved from the source `_meta` block. New fields can be
# added without bumping the schema version as long as existing clients ignore
# unknown keys (they do — see ts_client in inspector frontend).
_PRESERVED_META_FIELDS = (
    "padding",
    "aligner_model",
    "method",
    "beam",
    "shared_cmvn",
    "audio_source",
    "audio_reciter",
    "created_at",
)

SCHEMA_VERSION = 1

# Aligner provenance carried into the slim segment-array `_meta`. Reciter,
# url_template and audio_urls are deliberately excluded: the slug is the path
# and the catalog / audio-manifest sidecar is the ground truth for audio.
_SEGMENT_META_PROVENANCE = (
    "padding",
    "beam",
    "method",
    "aligner_model",
    "shared_cmvn",
    "audio_source",
    "created_at",
)

# v5 added the 6th word slot ``cells[]`` — per-character phoneme cells from the
# phonemizer's ``character_phoneme_mappings()`` (see
# ``qua_sdk.components.timing.lib.cells._stamp_cells`` and
# ``qua_shared/ts_shard_cells.py``). v6 carries two extra phonemizer-owned cell
# facts so the FE never infers phonology: the canonical shaddah composed into a
# geminated base cell's ``chars``, and a ``share_group`` on the vowel-absorbed
# haraka of a cross-word idgham. The cell-row structure is unchanged.
SEGMENT_SCHEMA_VERSION = 6


def _filter_mfa_failures(failures: list[dict] | None, chapter: int) -> list[dict]:
    """Keep only `_meta.mfa_failures` entries belonging to this chapter."""
    if not failures:
        return []
    out: list[dict] = []
    for fail in failures:
        verse = str(fail.get("verse", ""))
        if not verse:
            continue
        try:
            ch = int(verse.split(":", 1)[0])
        except ValueError:
            continue
        if ch == chapter:
            out.append(fail)
    return out


def _slice_audio_urls(audio_urls_fallback: dict | None, chapter: int) -> dict:
    """Return only URL entries for `chapter` (verse keys like `1:1`).

    Per-surah audio manifests use chapter-numeric keys (`"1"`, `"2"`); per-ayah
    manifests use `"<surah>:<ayah>"`. Both shapes are scoped here.
    """
    if not audio_urls_fallback:
        return {}
    out: dict = {}
    str_chapter = str(chapter)
    for k, v in audio_urls_fallback.items():
        if k == "_meta":
            continue
        if k == str_chapter:
            # by_surah single-key entry — keep as-is.
            out[k] = v
            continue
        if ":" in k and k.startswith(f"{chapter}:"):
            out[k] = v
    return out


def split_to_shards(
    timestamps_full_doc: dict,
    *,
    reciter: str,
    audio_category: str,
    url_template: str,
    audio_urls_fallback: dict | None = None,
) -> dict[int, dict]:
    """Split a `timestamps_full.json` into per-chapter shard documents.

    Args:
        timestamps_full_doc: parsed `timestamps_full.json` (top-level
            `_meta` plus verse-keyed entries like `"1:1"`).
        reciter: slug stamped into each shard's `_meta`.
        audio_category: ``"by_surah"`` or ``"by_ayah"``.
        url_template: protocol-stripped template (e.g.
            ``everyayah.com/data/Saad_Al_Ghamdi_40kbps/{surah:03d}{ayah:03d}.mp3``).
            Empty string falls back to per-verse `audio_urls`.
        audio_urls_fallback: full `data/audio/<source>/<reciter>.json`
            content (with `_meta`) — only consulted when ``url_template`` is
            empty. The relevant slice is inlined into each shard's `_meta`.

    Returns:
        ``{chapter: shard_doc}`` mapping. Each shard_doc is a dict with a
        `_meta` block plus the chapter's verse rows in canonical sort order.
    """
    src_meta = timestamps_full_doc.get("_meta", {}) or {}
    chapters: dict[int, dict] = {}

    # Group verse rows by chapter.
    for key, val in timestamps_full_doc.items():
        if key.startswith("_"):
            continue
        # Compound keys ("37:151:3-37:152:2") are sorted into the
        # surah of the *start* verse. Their `_provenance` carries
        # the actual verse_keys for downstream rendering.
        first_part = key.split("-", 1)[0]
        try:
            chapter = int(first_part.split(":", 1)[0])
        except (ValueError, IndexError):
            continue
        chapters.setdefault(chapter, {})[key] = val

    # Build each shard with its own `_meta`.
    out: dict[int, dict] = {}
    for chapter, verses in chapters.items():
        meta: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "reciter": reciter,
            "chapter": chapter,
            "audio_category": audio_category,
            "url_template": url_template or "",
        }
        # Preserve aligner-side meta fields when present.
        for field in _PRESERVED_META_FIELDS:
            if field in src_meta:
                meta[field] = src_meta[field]

        # Per-chapter mfa_failures slice — keeps the existing validation
        # surface (boundary panel + failure list) reachable from a single
        # shard fetch.
        failures = _filter_mfa_failures(src_meta.get("mfa_failures"), chapter)
        if failures:
            meta["mfa_failures"] = failures

        # Audio URL fallback only when the template couldn't be derived.
        if not url_template:
            sliced = _slice_audio_urls(audio_urls_fallback, chapter)
            if sliced:
                meta["audio_urls"] = sliced

        # Sort verse keys for deterministic byte-output → stable hashes.
        shard = {"_meta": meta}
        for k in sorted(verses.keys(), key=_verse_key_sort):
            shard[k] = verses[k]
        out[chapter] = shard

    return out


def _normalize_audio_category(audio_category: str) -> str:
    """Map the pipeline's internal category to the shard convention.

    The pipeline carries ``by_surah_audio`` / ``by_ayah_audio`` internally;
    shards expose the bare ``by_surah`` / ``by_ayah``.
    """
    cat = str(audio_category or "")
    if cat.endswith("_audio"):
        cat = cat[: -len("_audio")]
    return cat


def build_segment_shards(
    v2_doc: dict,
    *,
    audio_category: str,
    src_meta: dict | None = None,
) -> dict[int, dict]:
    """Build per-chapter temporal segment-array shards from a v2 raw document.

    ``v2_doc`` is the ``build_raw_v2`` shape — ``{output_key: [occurrence, ...]}``
    plus ``_meta``, where each occurrence is the normalized form
    ``{"ch_ref", "seg_index", "matched_ref", "time_start", "time_end",
    "words_by_verse": {verse_key: [word, ...]}, "segment_uid"}`` and each word
    is ``[widx, start_ms, end_ms, [[char,s,e]...], [[phone,s,e]...]]``.

    Every accepted occurrence becomes one segment entry verbatim (RAW — no
    dedup at write). Segments within a chapter are emitted in recitation order
    (sorted by ``time_start``). ``ref`` is always the occurrence's single home
    verse; cross-verse occurrences (compound output keys / ``_transitions``)
    are rejected — the TS job blocks compound cross-verse refs upstream so the
    bucket never carries them.

    Returns ``{chapter: shard_doc}`` where ``shard_doc`` is
    ``{"_meta": {schema_version, chapter, audio_category, <provenance>},
    "segments": [{"ref", "t": [start, end], "words": [...]}, ...]}``.
    """
    src_meta = src_meta or (v2_doc.get("_meta") or {})
    cat = _normalize_audio_category(audio_category)

    # Group occurrences by chapter (derived from each segment's single-verse ref).
    by_chapter: dict[int, list[dict]] = {}
    for key, occs in v2_doc.items():
        if key == "_meta":
            continue
        if "-" in key:
            raise ValueError(
                f"compound cross-verse output key {key!r} cannot be emitted as a "
                "single-verse segment shard"
            )
        if not isinstance(occs, list):
            continue
        for occ in occs:
            ref, words = _occurrence_to_segment(occ)
            # Chapter from the single-verse ref ("surah:ayah") so both by_surah
            # (chapter ref "1") and by_ayah (chapter ref "2:255") land correctly.
            try:
                chapter = int(ref.split(":", 1)[0])
            except (ValueError, TypeError):
                continue
            entry = {
                "ref": ref,
                "t": [occ["time_start"], occ["time_end"]],
                "words": words,
            }
            by_chapter.setdefault(chapter, []).append((occ, entry))

    out: dict[int, dict] = {}
    for chapter, pairs in by_chapter.items():
        # Recitation order: sort by segment start, tie-break on seg_index so
        # output is deterministic for coincident starts.
        pairs.sort(key=lambda p: (p[1]["t"][0], p[0].get("seg_index", 0)))
        meta: dict[str, Any] = {
            "schema_version": SEGMENT_SCHEMA_VERSION,
            "chapter": chapter,
            "audio_category": cat,
        }
        for field in _SEGMENT_META_PROVENANCE:
            if field in src_meta:
                meta[field] = src_meta[field]
        out[chapter] = {"_meta": meta, "segments": [p[1] for p in pairs]}
    return out


def _occurrence_to_segment(occ: dict) -> tuple[str, list]:
    """Return ``(ref, words)`` for a single-verse occurrence.

    The occurrence's ``words_by_verse`` must carry exactly one verse (its home
    verse) — guaranteed for single-verse refs. Raises on a cross-verse
    occurrence (more than one verse routed), which must never reach the writer.
    """
    wbv = occ.get("words_by_verse") or {}
    if len(wbv) != 1:
        raise ValueError(
            f"occurrence (matched_ref={occ.get('matched_ref')!r}) routes "
            f"{len(wbv)} verses; a segment shard ref must be a single verse"
        )
    ref, words = next(iter(wbv.items()))
    return ref, words


def _verse_key_sort(key: str) -> tuple[int, int, int]:
    """Sort key for verse refs. Compound refs sort by their start tuple."""
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
    re-running the build with unchanged input produces byte-identical
    output (load-bearing for the hash-diff cache).
    """
    import orjson

    payload = orjson.dumps(shard_doc)
    return gzip.compress(payload, compresslevel=6, mtime=0)


def sha256_hex(b: bytes) -> str:
    """SHA-256 hex digest of `b`. Used by the manifest's shard_hashes index."""
    return hashlib.sha256(b).hexdigest()
