"""Publish-time boundary validators for v2 dataset/release artifacts.

Four hard-fail checks per the v2 plan §Boundary enforcement. Called from both
``scripts/jobs/publish_hf.py`` and ``scripts/jobs/cut_release.py`` *before* the
artifact is written. Failures block the publish and surface the offending
verses in ``validation_summary``.

Input shape is the source-relative per-verse map produced by re-stitching
``reciters/<slug>/timestamps/<chapter>.json.gz`` shards back together. Each
verse entry is the canonical projection used by the FE today:

    {
      "verse_start_ms": int,
      "verse_end_ms":   int,
      "duration_ms":    int,            # verse_end - verse_start
      "words":          [(widx, s, e), ...],
      "segments":       [(word_from, word_to, s, e), ...],
    }

Times throughout are source-relative ms.
"""

from __future__ import annotations

from typing import Iterable


# A single failure record. ``violation`` is one of:
#   "word_bleed_first" / "word_bleed_last"  — first/last word extends past verse clip
#   "duration_arithmetic"                   — duration_ms != verse_end - verse_start
#   "intra_segment_gap"                     — adjacent words within a segment have a gap
#   "coverage_gap"                          — widx 1..N not all present in this verse
class Violation(dict):
    """Plain dict subclass — JSON-serializable, schema-stable."""


def _violation(ref: str, kind: str, **details) -> Violation:
    return Violation(ref=ref, violation=kind, **details)


def check_word_bleed(ref: str, verse: dict) -> list[Violation]:
    """Word-bleed: first word start >= verse start, last word end <= verse end.

    Pathological if violated — a verse clip should not start mid-word or end mid-word.
    """
    words = verse.get("words") or []
    if not words:
        return []
    v_start = int(verse["verse_start_ms"])
    v_end = int(verse["verse_end_ms"])
    out: list[Violation] = []
    first_start = int(words[0][1])
    last_end = int(words[-1][2])
    if first_start < v_start:
        out.append(_violation(ref, "word_bleed_first",
                              word_start=first_start, verse_start=v_start,
                              delta=v_start - first_start))
    if last_end > v_end:
        out.append(_violation(ref, "word_bleed_last",
                              word_end=last_end, verse_end=v_end,
                              delta=last_end - v_end))
    return out


def check_duration_arithmetic(ref: str, verse: dict) -> list[Violation]:
    """``duration_ms == verse_end_ms - verse_start_ms``. Pure check."""
    v_start = int(verse["verse_start_ms"])
    v_end = int(verse["verse_end_ms"])
    duration = int(verse.get("duration_ms", v_end - v_start))
    expected = v_end - v_start
    if duration != expected:
        return [_violation(ref, "duration_arithmetic",
                           duration_ms=duration, expected=expected,
                           verse_start_ms=v_start, verse_end_ms=v_end)]
    return []


def check_intra_segment_gapless(ref: str, verse: dict) -> list[Violation]:
    """Adjacent words within a segment are gapless (``w_(i+1).start == w_i.end``).

    Gaps are allowed only across segment boundaries. The pipeline applies
    padding + silence removal post-MFA, so MFA's intra-segment boundaries
    are gapless by design — a non-zero gap inside a segment means the
    invariant broke somewhere.
    """
    segments = verse.get("segments") or []
    words = verse.get("words") or []
    if not segments or len(words) < 2:
        return []
    # widx → (start, end) lookup
    wmap: dict[int, tuple[int, int]] = {}
    for w in words:
        wmap[int(w[0])] = (int(w[1]), int(w[2]))

    out: list[Violation] = []
    for seg in segments:
        w_from, w_to = int(seg[0]), int(seg[1])
        if w_to <= w_from:
            continue
        for widx in range(w_from, w_to):
            cur = wmap.get(widx)
            nxt = wmap.get(widx + 1)
            if cur is None or nxt is None:
                continue
            if nxt[0] != cur[1]:
                out.append(_violation(ref, "intra_segment_gap",
                                      word_a=widx, word_b=widx + 1,
                                      a_end=cur[1], b_start=nxt[0],
                                      gap_ms=nxt[0] - cur[1]))
    return out


def check_coverage(ref: str, verse: dict, expected_words: int | None) -> list[Violation]:
    """Every widx in 1..N is covered. ``expected_words`` is the count from
    surah_info; if None the check degenerates to "no duplicate widx" (which
    is also fine — gaps from delete/failed_align are caller-handled separately).
    """
    words = verse.get("words") or []
    if not words:
        return []
    widxs = [int(w[0]) for w in words]
    seen = set(widxs)
    if expected_words is not None and expected_words > 0:
        missing = [i for i in range(1, expected_words + 1) if i not in seen]
        if missing:
            return [_violation(ref, "coverage_gap",
                               expected=expected_words,
                               present=sorted(seen),
                               missing=missing)]
    return []


def validate_verse(ref: str, verse: dict, *,
                   expected_words: int | None = None) -> list[Violation]:
    """Run every check on one verse. Returns the combined violation list."""
    out: list[Violation] = []
    out.extend(check_word_bleed(ref, verse))
    out.extend(check_duration_arithmetic(ref, verse))
    out.extend(check_intra_segment_gapless(ref, verse))
    out.extend(check_coverage(ref, verse, expected_words))
    return out


def validate_dataset(verses: dict[str, dict], *,
                     surah_info: dict | None = None) -> dict:
    """Run every check on every verse.

    Returns a ``validation_summary`` with the failure list + per-check counts:

      {
        "ok": bool,
        "verse_count": int,
        "violation_count": int,
        "by_kind": {kind: count, ...},
        "violations": [Violation, ...],
        "dropped_verses": [],  # caller fills if coverage_gap → drop
      }
    """
    expected_by_ref = _expected_words_index(surah_info) if surah_info else {}
    violations: list[Violation] = []
    for ref, verse in verses.items():
        if ref.startswith("_"):
            continue
        violations.extend(validate_verse(
            ref, verse, expected_words=expected_by_ref.get(ref)))
    by_kind: dict[str, int] = {}
    for v in violations:
        by_kind[v["violation"]] = by_kind.get(v["violation"], 0) + 1
    return {
        "ok": not violations,
        "verse_count": sum(1 for r in verses if not r.startswith("_")),
        "violation_count": len(violations),
        "by_kind": by_kind,
        "violations": violations,
        "dropped_verses": [],
    }


def _expected_words_index(surah_info: dict) -> dict[str, int]:
    """Build ``{"surah:ayah": num_words}`` from surah_info."""
    out: dict[str, int] = {}
    for surah_num, meta in surah_info.items():
        if surah_num.startswith("_"):
            continue
        for v in meta.get("verses", []) or []:
            ref = f"{surah_num}:{v.get('verse')}"
            n = v.get("num_words")
            if isinstance(n, int) and n > 0:
                out[ref] = n
    return out


# ---------------------------------------------------------------------------
# Hard-fail kinds. Coverage gaps are reported but allow the verse to drop from
# the publish; the other three are flat-out illegal and abort.
# ---------------------------------------------------------------------------

HARD_FAIL_KINDS = (
    "word_bleed_first",
    "word_bleed_last",
    "duration_arithmetic",
    "intra_segment_gap",
)


def fatal_violations(violations: Iterable[Violation]) -> list[Violation]:
    return [v for v in violations if v.get("violation") in HARD_FAIL_KINDS]


class BoundaryValidationError(RuntimeError):
    """Raised by publish_hf / cut_release when fatal violations are present."""

    def __init__(self, summary: dict):
        self.summary = summary
        fatal = fatal_violations(summary.get("violations") or [])
        msg = (f"{len(fatal)} fatal boundary violation(s); "
               f"first: {fatal[0] if fatal else '<none>'}")
        super().__init__(msg)
