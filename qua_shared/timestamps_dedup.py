"""Raw timestamps v2 builder + the consumer-side segment-array projection.

The bucket per-chapter shard stores every accepted segment raw, in recitation
order, with no dedup at write. Two faces live here:

- ``build_raw_v2`` records EVERY accepted segment as its own *occurrence*
  under its output key (compound key for cross-verse; ``"_transitions"``
  for non-verse tokens), with the segment's words verbatim — no
  repeat-pass skip, no word merge. The offline writer and the one-off
  reshape both feed this in-memory doc to ``build_segment_shards``.
- ``project_segment_shard`` is the consumer-side projection for the temporal
  segment-array bucket shape: consumers (releases, the HF dataset) reduce a
  verse's segments to a single canonical take via completion-based occasion
  dedup. See ``docs/planning/ts-segment-array-migration.md``.

``build_raw_v2`` reuses the pipeline's ``_normalize_from_results`` +
``_matched_ref_to_output_key`` so there is exactly one conversion path; one-
directional — the pipeline does not import this module. ``is_v2`` is the shape
discriminator the reshape CLI uses.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from qua_shared.timestamps_pipeline import (
    _matched_ref_to_output_key,
    _normalize_from_results,
)

V2_SCHEMA_VERSION = 2

# Output key for accepted non-verse (transition) segments. The segment-array
# writer rejects these (and compound cross-verse keys); the TS job blocks them
# upstream so they never reach the bucket.
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


def is_v2(doc: dict) -> bool:
    """True if ``doc`` has list-valued payload entries (occurrence list or the
    reshaped segment array), False for a verse-map (dict-valued) document.

    Detected from the first non-meta entry. The reshape CLI pairs this with the
    top-level ``segments`` key to tell the occurrence-list source from the
    already-reshaped target (both are list-valued).
    """
    for key, val in doc.items():
        if key == "_meta":
            continue
        return isinstance(val, list)
    return False


# ---------------------------------------------------------------------------
# Segment-array shard → canonical verse-map (completion-based occasion dedup)
#
# The bucket stores every accepted segment raw, in recitation order. Consumers
# (releases, the HF dataset) project a canonical single take per verse with this
# pure projection. See `docs/planning/ts-segment-array-migration.md`.
# ---------------------------------------------------------------------------


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


def _first_widx(seg: dict) -> int | None:
    """First word index in a segment, or None if it carries no words."""
    words = seg.get("words") or []
    return int(words[0][0]) if words else None


def _trim_leading_false_start(kept: list[dict], target: set[int]) -> list[dict]:
    """Drop a redundant leading false-start from a canonical run.

    A false-start is an abandoned attempt: the reciter recites a leading prefix,
    then restarts the verse from word 1 and completes it. Symmetric to the
    trailing trim — keep only from the LAST segment that restarts at word 1 whose
    run still covers the whole verse ``target``; everything before it is
    redundant. Mid-verse lookbacks (a backward jump to a non-first word) never
    restart at word 1, so they are untouched. The restart is a natural segment
    boundary, so trimming stays audio-contiguous.
    """
    if not target:
        return kept
    best = 0
    for r in range(1, len(kept)):
        if _first_widx(kept[r]) != 1:
            continue
        cov: set[int] = set()
        for seg in kept[r:]:
            cov |= _seg_widx_set(seg)
        if target.issubset(cov):
            best = r
    return kept[best:]


def _canonical_verse(words: list, segs: list[dict]) -> dict:
    """Assemble the canonical verse-map value from the chosen occasion's words.

    Concatenates the accumulated word lists (recitation order, loops retained)
    and stamps ``verse_start_ms`` / ``verse_end_ms`` as the span covering every
    kept segment AND every word/letter time. A word or letter can bleed a few ms
    past its segment's ``t`` bound, so the clip must reach the furthest word/letter
    end or it would truncate the final word's tail (and verse_end < a word's end
    violates the "all times within [verse_start, verse_end]" invariant).

    Also carries ``segments``: the kept segments as half-open occurrence ranges
    into the flat ``words`` list (``words == concat(seg["words"] for seg in
    segs)``), so a downstream consumer recovers the exact word OCCURRENCE that
    belongs to each segment. This is the only faithful source for a segment's
    boundary when its first/last word index is repeated elsewhere in the verse
    (a look-back) — an index-keyed lookup would collapse to the wrong occurrence
    and overlap adjacent segments. Each entry is ``{ref, w_from, w_to, occ_start,
    occ_end, start_ms, end_ms}`` (ms are source-relative; word-less no-match
    segments are omitted, they contribute nothing to ``words``).
    """
    starts = [int(s["t"][0]) for s in segs]
    ends = [int(s["t"][1]) for s in segs]
    for w in words:
        starts.append(int(w[1]))
        ends.append(int(w[2]))
        for lt in w[3] if len(w) > 3 else []:
            if lt[1] is not None:
                starts.append(int(lt[1]))
            if lt[2] is not None:
                ends.append(int(lt[2]))
    seg_spans: list[dict] = []
    cursor = 0
    for s in segs:
        sw = s.get("words") or []
        n = len(sw)
        if n:
            seg_spans.append(
                {
                    "ref": s.get("ref"),
                    "w_from": int(sw[0][0]),
                    "w_to": int(sw[-1][0]),
                    "occ_start": cursor,
                    "occ_end": cursor + n,
                    "start_ms": int(sw[0][1]),
                    "end_ms": int(sw[-1][2]),
                }
            )
        cursor += n
    return {
        "words": words,
        "verse_start_ms": min(starts),
        "verse_end_ms": max(ends),
        "segments": seg_spans,
    }


def project_segment_shard(shard: dict) -> dict[str, dict]:
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
      - canonical = the segments around the completing one, with BOTH a leading
        false-start (an abandoned prefix before a restart at word 1) and trailing
        post-completion redundancy trimmed; the middle of audio is never cut;
      - among multiple completing occasions, pick the EARLIEST (first recited);
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
        n_words = max((wi for seg in verse_segs for wi in _seg_widx_set(seg)), default=0)
        target = set(range(1, n_words + 1))

        chosen = _choose_occasion(occasions, target)
        out[ref] = _project_occasion(chosen, target)
    return out


def select_complete_verses(
    projected: dict[str, dict],
    word_counts: dict[tuple[int, int], int],
) -> tuple[dict[str, dict], list[str]]:
    """Drop verses whose canonical take is missing any reference word index.

    A publish-time gate layered on top of ``project_segment_shard`` (NOT part of
    the projection — the editor/TS-tab read path must keep showing incomplete
    verses so reviewers can fix them; only the release/dataset adapters gate).

    Completeness is by word INDEX, mirroring the editor's missing-words check
    (``inspector/services/validation/_missing.py``): a verse is complete iff
    ``{1..N_ref}`` is a subset of the indices that carry a published word timing.
    That covered set is the words actually present in the artifact, so it is the
    correct "does this verse contain every word" test — it can differ marginally
    from the matched_ref-span definition when MFA timed fewer words than a
    segment's span. Verses with no known reference count are kept (fail-open).

    Returns ``(kept_map, sorted_dropped_refs)``.
    """
    kept: dict[str, dict] = {}
    dropped: list[str] = []
    for ref, v in projected.items():
        try:
            surah_s, ayah_s = ref.split(":", 1)
            key = (int(surah_s), int(ayah_s))
        except (ValueError, AttributeError):
            kept[ref] = v
            continue
        n_ref = word_counts.get(key)
        if not n_ref:
            kept[ref] = v
            continue
        covered = {int(w[0]) for w in (v.get("words") or [])}
        if set(range(1, n_ref + 1)).issubset(covered):
            kept[ref] = v
        else:
            dropped.append(ref)
    return kept, sorted(dropped)


def _choose_occasion(occasions: list[list[dict]], target: set[int]) -> list[dict]:
    """Pick the canonical occasion: the EARLIEST completing one.

    Falls back to the widest-coverage occasion when none complete.
    """
    completing = [occ for occ in occasions if _completes_at(occ, target) is not None]
    if completing:
        return completing[0]  # earliest completing (first recited)
    # No occasion completes — keep the one with the widest word coverage.
    return max(
        occasions,
        key=lambda occ: len(set().union(*(_seg_widx_set(s) for s in occ)) if occ else set()),
    )


def _project_occasion(occasion: list[dict], target: set[int]) -> dict:
    """Trim leading false-start + trailing redundancy, then assemble the value."""
    comp = _completes_at(occasion, target)
    kept = occasion[: comp + 1] if comp is not None else occasion
    kept = _trim_leading_false_start(kept, target)
    words: list = []
    for seg in kept:
        words.extend(seg.get("words") or [])
    return _canonical_verse(words, kept)
