"""Raw (unfiltered) timestamps v2 + the canonical dedup projection.

The MFA pipeline historically produced an already-deduped, verse-keyed
``timestamps_full.json`` (one merged entry per verse — re-recitations and
cross-verse bleed collapsed at write time). v2 stops discarding that
information at the raw level:

- ``build_raw_v2`` records EVERY accepted segment as its own *occurrence*
  under its output key (compound key for cross-verse; ``"_transitions"``
  for non-verse tokens), with the segment's words verbatim — no
  repeat-pass skip, no word merge.
- ``canonical_occurrence`` projects a v2 document back to the historical
  deduped verse map, so consumers that want the canonical single take
  (the Timestamps tab, the dataset) get byte-identical output to today.

Both faces reuse the pipeline's shared core: ``build_raw_v2`` and
``build_outputs`` feed ``_normalize_from_results``; ``canonical_occurrence``
and ``build_outputs`` feed ``_dedup_core``. There is exactly one
implementation of conversion and of dedup, so the projection can never
drift from what the pipeline wrote. See
``docs/planning/inspector-deploy/v2/phases/13-timestamps-job.md``.

``project_segment_shard`` is the consumer-side projection for the temporal
segment-array bucket shape: the bucket stores every segment raw, and consumers
(releases, the HF dataset) reduce a verse's segments to a single canonical take
via completion-based occasion dedup. See
``docs/planning/ts-segment-array-migration.md``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

# Conversion + dedup live in the pipeline today (alongside the helpers);
# this module imports them so there is a single implementation. One-
# directional: the pipeline does not import this module.
from scripts.lib.timestamps_pipeline import (
    _normalize_from_results,
    _dedup_core,
    _matched_ref_to_output_key,
)

V2_SCHEMA_VERSION = 2

# Bucket for accepted non-verse (transition) segments — kept so the
# canonical projection can reproduce the pipeline exactly, but excluded
# from per-chapter shards (split_to_shards skips ``_``-prefixed keys).
_TRANSITION_KEY = "_transitions"


def build_raw_v2(
    chapters: list[dict],
    results_by_ch: dict[int, list[tuple[int, dict]]],
    audio_category: str,
) -> dict[str, Any]:
    """Build the unfiltered v2 timestamps document from MFA results.

    Returns ``{"_meta": {"mfa_failures": [...], "schema_version": 2},
    "<output_key>": [occurrence, ...]}`` where ``output_key`` is the
    single-verse key (``"1:1"``), the compound cross-verse key
    (``"1:1:3-1:2:2"``), or ``"_transitions"``. Each occurrence is the
    normalized shape from ``_normalize_from_results``::

        {"ch_ref", "seg_index", "matched_ref", "time_start", "time_end",
         "words_by_verse": {verse_key: [[widx, s, e, letters, phones]...]},
         "segment_uid"}

    NO repeat-pass skip and NO word merge — every accepted segment is a
    distinct occurrence. Failed segments are recorded only in
    ``_meta.mfa_failures`` (with ``seg`` + ref for run reconstruction).
    """
    norm, failures = _normalize_from_results(chapters, results_by_ch, audio_category)
    raw: dict[str, Any] = {}
    for occs in norm.values():
        for occ in occs:
            key = _matched_ref_to_output_key(occ["matched_ref"]) or _TRANSITION_KEY
            raw.setdefault(key, []).append(occ)
    for key in raw:
        raw[key].sort(key=lambda o: (o["ch_ref"], o["seg_index"]))
    raw["_meta"] = {"mfa_failures": failures, "schema_version": V2_SCHEMA_VERSION}
    return raw


def canonical_occurrence(
    v2_doc: dict[str, Any],
    audio_category: str,
    seed_existing: dict | None = None,
) -> dict[str, Any]:
    """Project a v2 raw document to the historical deduped verse map.

    Regroups occurrences (+ failures) by chapter via the occurrence's
    ``ch_ref``, reconstructs the positional ``matched_refs`` list each
    chapter needs for repeat-pass run detection, and runs the SAME
    ``_dedup_core`` the live pipeline uses. Returns ``full_data`` — the
    verse-keyed deduped map (byte-identical to the historical
    ``timestamps_full.json`` body).
    """
    occ_by_ch: dict[str, list] = defaultdict(list)
    refs_by_ch: dict[str, dict[int, str]] = defaultdict(dict)

    for key, occs in v2_doc.items():
        if key == "_meta":
            continue
        for occ in occs:
            ch = occ["ch_ref"]
            occ_by_ch[ch].append(occ)
            refs_by_ch[ch][occ["seg_index"]] = occ["matched_ref"]

    meta = v2_doc.get("_meta", {}) or {}
    for fail in (meta.get("mfa_failures") or []):
        ch = str(fail.get("verse", ""))
        seg = fail.get("seg")
        if seg is not None and ch in occ_by_ch:
            # Only fill run-reconstruction refs for chapters that produced
            # at least one occurrence (others contribute nothing to full_data).
            refs_by_ch[ch].setdefault(seg, fail.get("ref", ""))

    chapters_norm = []
    for ch, occs in occ_by_ch.items():
        seg_map = refs_by_ch[ch]
        max_idx = max(seg_map) if seg_map else -1
        matched_refs = [seg_map.get(i, "") for i in range(max_idx + 1)]
        chapters_norm.append({
            "ch_ref": ch,
            "matched_refs": matched_refs,
            "occurrences": sorted(occs, key=lambda o: o["seg_index"]),
        })

    full_data, _words = _dedup_core(
        chapters_norm, seed_existing,
        completed_surahs=set(), completed_refs=set(),
        refresh_surahs=None, audio_category=audio_category,
    )
    return full_data


def is_v2(doc: dict) -> bool:
    """True if ``doc`` is a v2 (occurrence-list) document, else v1 (verse-map).

    v2 verse values are lists of occurrences; v1 values are dicts
    (``{"words": [...], ...}``). Detected from the first non-meta entry.
    """
    for key, val in doc.items():
        if key == "_meta":
            continue
        return isinstance(val, list)
    return False


def project_chapter_shard(doc: dict, *, full: bool = False) -> dict:
    """Return the per-chapter shard document to serve to the Timestamps tab.

    - v1 doc → returned unchanged (back-compat for existing shards).
    - v2 doc, ``full=False`` → deduped to the historical verse-map shape via
      ``canonical_occurrence`` (the Timestamps tab sees today's single take).
    - v2 doc, ``full=True`` → returned unchanged (every occurrence; for the
      owner preview / aligner "show all" surface).

    ``_meta`` is preserved either way. ``audio_category`` is read from
    ``_meta`` (``"by_surah"`` / ``"by_ayah"`` or the ``_audio`` variants).
    """
    if not is_v2(doc) or full:
        return doc
    cat = (doc.get("_meta") or {}).get("audio_category") or "by_surah"
    deduped = canonical_occurrence(doc, cat)
    return {"_meta": doc.get("_meta", {}), **deduped}


# ---------------------------------------------------------------------------
# Segment-array shard → canonical verse-map (completion-based occasion dedup)
#
# The bucket stores every accepted segment raw, in recitation order. Consumers
# (releases, the HF dataset) project a canonical single take per verse with this
# pure projection. See `docs/planning/ts-segment-array-migration.md`.
# ---------------------------------------------------------------------------


def confidence_by_span(detailed: dict | None) -> dict[tuple[int, int], float]:
    """Build a ``{(time_start, time_end): confidence}`` lookup from detailed.json.

    Used to join per-segment alignment confidence onto segment-array shards for
    the highest-confidence pick in ``project_segment_shard``. ``(time_start,
    time_end)`` is unique per segment, so it keys cleanly. Returns an empty dict
    when ``detailed`` is missing or carries no confidences.
    """
    out: dict[tuple[int, int], float] = {}
    if not detailed:
        return out
    for entry in detailed.get("entries", []) or []:
        for seg in entry.get("segments", []) or []:
            conf = seg.get("confidence")
            if conf is None:
                continue
            ts = seg.get("time_start")
            te = seg.get("time_end")
            if ts is None or te is None:
                continue
            out[(int(ts), int(te))] = float(conf)
    return out


def _seg_widx_set(seg: dict) -> set[int]:
    """Word indices covered by one segment-array segment ``{ref, t, words}``.

    Each word is ``[widx, start_ms, end_ms, letters, phones]``.
    """
    return {int(w[0]) for w in (seg.get("words") or [])}


def _split_occasions(verse_segs: list[dict], foreign_starts: list[int]) -> list[list[dict]]:
    """Split a verse's time-ordered segments into occasions.

    An occasion is a maximal run adjacent in the chapter timeline with no other
    verse interleaved: a foreign segment whose start falls strictly between two
    consecutive same-verse segment starts breaks the run.
    """
    occasions: list[list[dict]] = []
    cur: list[dict] = []
    for seg in verse_segs:
        if cur:
            prev_start = cur[-1]["t"][0]
            this_start = seg["t"][0]
            if any(prev_start < ft < this_start for ft in foreign_starts):
                occasions.append(cur)
                cur = []
        cur.append(seg)
    if cur:
        occasions.append(cur)
    return occasions


def _completes_at(occasion: list[dict], target: set[int]) -> int | None:
    """Index of the segment that first reaches full coverage ``target``, else None.

    Coverage accumulates in time order; within-pass backward loops are retained
    verbatim (every segment's words contribute, none are deduped).
    """
    covered: set[int] = set()
    for i, seg in enumerate(occasion):
        covered |= _seg_widx_set(seg)
        if target.issubset(covered):
            return i
    return None


def _occasion_mean_confidence(
    occasion: list[dict], conf_by_span: dict[tuple[int, int], float] | None
) -> float | None:
    """Mean alignment confidence across an occasion's segments.

    Joins each segment to ``detailed.json`` by its ``(start_ms, end_ms)`` span
    (unique per segment). Returns None if no segment has a confidence, so the
    caller can fall back to the earliest completing occasion.
    """
    if not conf_by_span:
        return None
    vals = [
        conf_by_span[(seg["t"][0], seg["t"][1])]
        for seg in occasion
        if (seg["t"][0], seg["t"][1]) in conf_by_span
    ]
    return sum(vals) / len(vals) if vals else None


def _canonical_verse(words: list, segs: list[dict]) -> dict:
    """Assemble the canonical verse-map value from the chosen occasion's words.

    Concatenates the accumulated word lists (recitation order, loops retained)
    and stamps ``verse_start_ms`` / ``verse_end_ms`` from the segment span so
    downstream tier/dataset builders get the clip boundary for free.
    """
    verse_start = segs[0]["t"][0]
    verse_end = max(int(s["t"][1]) for s in segs)
    return {
        "words": words,
        "verse_start_ms": int(verse_start),
        "verse_end_ms": int(verse_end),
    }


def project_segment_shard(
    shard: dict,
    *,
    conf_by_span: dict[tuple[int, int], float] | None = None,
) -> dict[str, dict]:
    """Project a segment-array shard to the canonical per-verse map.

    ``shard`` is the bucket artifact ``{"_meta": {...}, "segments":
    [{"ref", "t": [start_ms, end_ms], "words": [...]}, ...]}`` — every accepted
    segment raw, in recitation order. Returns ``{ref: {"words", "verse_start_ms",
    "verse_end_ms"}}`` carrying one canonical take per verse (``_meta`` dropped).

    Dedup (completion-based, audio-sequential):
      - group each verse's segments into OCCASIONS (maximal runs adjacent in the
        chapter timeline with no other verse interleaved);
      - within an occasion accumulate word coverage in time order, retaining
        within-pass backward loops verbatim; the occasion COMPLETES when coverage
        first reaches ``{1..N}`` (N = max word index across all the verse's
        segments — every recited word);
      - canonical = the segments up to and including the completing one (trailing
        post-completion redundancy trimmed; never cut the middle of audio);
      - among multiple completing occasions, pick the HIGHEST mean alignment
        confidence (joined via ``conf_by_span``); fall back to the EARLIEST
        completing occasion when confidence is unavailable;
      - verses that never complete in any single occasion fall back to the
        occasion with the widest coverage (longest contiguous take).
      - non-canonical occasions are dropped.
    """
    segments = [s for s in (shard.get("segments") or []) if s.get("ref")]
    # Recitation order (the shard is written sorted; sort defensively).
    segments.sort(key=lambda s: s["t"][0])

    by_verse: dict[str, list[dict]] = defaultdict(list)
    for seg in segments:
        by_verse[seg["ref"]].append(seg)
    seg_starts_by_verse = {ref: [s["t"][0] for s in segs] for ref, segs in by_verse.items()}

    out: dict[str, dict] = {}
    for ref, verse_segs in by_verse.items():
        # Foreign starts = every OTHER verse's segment-start time.
        foreign_starts: list[int] = []
        for other_ref, starts in seg_starts_by_verse.items():
            if other_ref != ref:
                foreign_starts.extend(starts)
        foreign_starts.sort()

        occasions = _split_occasions(verse_segs, foreign_starts)
        n_words = max(
            (wi for seg in verse_segs for wi in _seg_widx_set(seg)), default=0
        )
        target = set(range(1, n_words + 1))

        chosen = _choose_occasion(occasions, target, conf_by_span)
        out[ref] = _project_occasion(chosen, target)
    return out


def _choose_occasion(
    occasions: list[list[dict]],
    target: set[int],
    conf_by_span: dict[tuple[int, int], float] | None,
) -> list[dict]:
    """Pick the canonical occasion (completing, then highest mean confidence).

    Falls back to the earliest completing occasion when no confidence is
    available, and to the widest-coverage occasion when none complete.
    """
    completing = [occ for occ in occasions if _completes_at(occ, target) is not None]
    if completing:
        ranked = [
            (i, _occasion_mean_confidence(occ, conf_by_span))
            for i, occ in enumerate(completing)
        ]
        if any(conf is not None for _, conf in ranked):
            # Highest mean confidence; tie-break on earliest (lower index).
            best_i = max(
                ranked, key=lambda ic: (ic[1] if ic[1] is not None else -1.0, -ic[0])
            )[0]
            return completing[best_i]
        return completing[0]  # earliest completing — confidence unavailable
    # No occasion completes — keep the one with the widest word coverage.
    return max(
        occasions,
        key=lambda occ: len(set().union(*(_seg_widx_set(s) for s in occ)) if occ else set()),
    )


def _project_occasion(occasion: list[dict], target: set[int]) -> dict:
    """Trim trailing post-completion segments, then assemble the verse value."""
    comp = _completes_at(occasion, target)
    kept = occasion[: comp + 1] if comp is not None else occasion
    words: list = []
    for seg in kept:
        words.extend(seg.get("words") or [])
    return _canonical_verse(words, kept)
