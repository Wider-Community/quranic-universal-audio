"""One-off RESHAPE: v2 occurrence-list shard → temporal segment-array shard.

The bucket per-chapter shard (`reciters/<slug>/timestamps/<ch>.json.gz`)
historically stored a **v2 occurrence-list**: ``{"_meta", "<verse>": [occurrence,
...], ...}`` keyed by verse, each occurrence carrying
``{ch_ref, seg_index, matched_ref, time_start, time_end, words_by_verse,
segment_uid}``. The inspector read-path re-deduped + re-encoded that on every cold
miss. The TARGET shape is the consumer-shaped temporal segment array

    {"_meta": {schema_version: 2, chapter, audio_category, <aligner provenance>},
     "segments": [{"ref": "surah:ayah", "t": [start_ms, end_ms],
                   "words": [[widx, s, e, [[char,s,e]...], [[phone,s,e]...]], ...]},
                  ...]}                       # recitation (time_start) order

so the read path becomes a byte pass-through and the bucket is clean for external
consumers. See ``docs/planning/ts-segment-array-migration.md``.

This module is the **pure** transform for the one-off migration of existing
shards (RESHAPE, not regeneration — no MFA re-run). It reuses
``timestamps_shards.build_segment_shards`` so a reshaped shard is byte-shape
identical to what the offline writer emits for the equivalent occurrence set
(the writer and the reshape converge on the SAME segment-array shape — there is
exactly one segment-array builder). A per-chapter occurrence-list shard is just a
single-chapter slice of the ``v2_doc`` ``build_segment_shards`` already consumes.

Detection of an already-reshaped shard reuses ``timestamps_dedup.is_v2`` plus the
top-level ``segments`` key: ``is_v2`` returns True for BOTH shapes (the target's
``segments`` value is a list), so the ``segments`` key is the discriminator. No
Flask, no bucket I/O — the CLI (``qua_jobs/reshape_timestamps_shards.py``)
owns local-directory reads/writes and bucket delete-listing.
"""

from __future__ import annotations

from typing import Any

from qua_shared.timestamps_dedup import is_v2
from qua_shared.timestamps_shards import build_segment_shards

# Top-level key that marks a shard as already in the TARGET segment-array shape.
SEGMENTS_KEY = "segments"


def classify_shard(shard: dict) -> str:
    """Classify a per-chapter shard document by shape.

    Returns one of:
      - ``"target"``    — already the segment-array shape (has top-level
        ``segments``). Reshape is a no-op.
      - ``"v2"``        — v2 occurrence-list (verse keys → occurrence lists).
        Needs reshaping.
      - ``"v1"``        — pre-v2 verse-map (verse keys → dicts). Not handled by
        the reshape (the audit found 0 v1 among the live shadowing ``.json``s
        that matter; v1 shards are reported + skipped by the CLI).
      - ``"empty"``     — no non-``_meta`` keys.
    """
    has_payload = any(k != "_meta" for k in shard)
    if not has_payload:
        return "empty"
    if SEGMENTS_KEY in shard:
        return "target"
    return "v2" if is_v2(shard) else "v1"


def reshape_shard(shard: dict) -> dict[str, Any]:
    """Reshape one v2 occurrence-list shard → the TARGET segment-array shard.

    ``shard`` is a single per-chapter v2 document
    ``{"_meta": {...}, "<verse>": [occurrence, ...], ...}``. The aligner
    provenance + ``audio_category`` are read from the shard's own ``_meta``.

    Returns ``{"_meta": {schema_version: 2, chapter, audio_category,
    <provenance>}, "segments": [{ref, t, words}, ...]}`` in recitation order.

    Convergence: this delegates to ``build_segment_shards`` (the single
    segment-array builder the offline writer uses), so the output is byte-shape
    identical to a freshly-generated shard for the same occurrence set. The
    occurrence-list shard is passed as the ``v2_doc`` directly — a per-chapter
    shard is one chapter of the multi-chapter doc that function consumes.

    Raises ``ValueError`` if the shard is not a v2 occurrence-list, if it carries
    a compound cross-verse output key (``build_segment_shards`` rejects these —
    the TS job blocks them upstream), or if it does not flatten to exactly one
    chapter.
    """
    kind = classify_shard(shard)
    if kind == "target":
        raise ValueError("shard is already in the target segment-array shape")
    if kind == "empty":
        raise ValueError("shard has no occurrence entries to reshape")
    if kind == "v1":
        raise ValueError(
            "shard is a pre-v2 verse-map (not an occurrence list); reshape only "
            "handles v2 occurrence-list shards"
        )

    src_meta = shard.get("_meta") or {}
    # audio_category lives on the shard itself (e.g. "by_surah_audio");
    # build_segment_shards normalizes the "_audio" suffix away.
    audio_category = src_meta.get("audio_category") or "by_surah"

    chapter_shards = build_segment_shards(
        shard, audio_category=audio_category, src_meta=src_meta
    )
    if len(chapter_shards) != 1:
        raise ValueError(
            f"expected a single chapter, got {sorted(chapter_shards)} — a "
            "per-chapter shard must contain occurrences for exactly one surah"
        )
    (_chapter, out), = chapter_shards.items()
    return out
