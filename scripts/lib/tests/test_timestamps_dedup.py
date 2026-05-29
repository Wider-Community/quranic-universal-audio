"""Tests for v2 raw timestamps (build_raw_v2) + canonical dedup projection.

The load-bearing test is ``test_round_trip_matches_build_outputs``:
``canonical_occurrence(build_raw_v2(x))`` must equal the pipeline's
``build_outputs(x)`` byte-for-byte. Because both reuse the same
``_normalize_from_results`` + ``_dedup_core``, equality is structural —
this guards the v2 reshape (occurrence split + chapter regrouping +
matched_refs reconstruction), not the dedup logic itself.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.lib.timestamps_dedup import build_raw_v2, canonical_occurrence  # noqa: E402
from scripts.lib.timestamps_pipeline import build_outputs  # noqa: E402

CAT = "by_surah_audio"


def _ok(locations, t0=0.0, step=0.5):
    """Synthetic MFA 'ok' result: one word per location, sequential times (s)."""
    words = []
    for i, loc in enumerate(locations):
        s = t0 + i * step
        words.append({
            "location": loc, "start": s, "end": s + step,
            "letters": [], "phones": [],
        })
    return {"status": "ok", "words": words}


def _chapter():
    return {
        "ref": "1",
        "segments": [
            {"matched_ref": "1:1:1-1:1:4", "time_start": 0, "time_end": 1000},
            # re-recitation of 1:1 — the pipeline DROPS this run
            {"matched_ref": "1:1:1-1:1:4", "time_start": 2000, "time_end": 3000},
            # 1:2 — MFA failed
            {"matched_ref": "1:2:1-1:2:3", "time_start": 3000, "time_end": 4000},
            # cross-verse bleed seg
            {"matched_ref": "1:2:1-1:3:2", "time_start": 4000, "time_end": 5000,
             "segment_uid": "uid-xv"},
        ],
    }


def _results():
    return {0: [
        (0, _ok(["1:1:1", "1:1:2"])),
        (1, _ok(["1:1:1", "1:1:2"], t0=2.0)),
        (2, {"status": "error", "error": "timeout"}),
        (3, _ok(["1:2:1", "1:3:1"], t0=4.0)),
    ]}


def _build_outputs(chapter, results):
    return build_outputs(
        results, None,
        chapters=[chapter], completed_surahs=set(), completed_refs=set(),
        refresh_surahs=None, audio_category=CAT,
    )


# --- build_raw_v2: occurrence preservation (the whole point of v2) ---

def test_repeated_verse_preserves_both_occurrences():
    raw = build_raw_v2([_chapter()], _results(), CAT)
    occs = raw["1:1"]
    assert len(occs) == 2, "both re-recitation runs must be preserved (not deduped)"
    assert [o["seg_index"] for o in occs] == [0, 1]
    assert all(set(o["words_by_verse"]) == {"1:1"} for o in occs)


def test_cross_verse_kept_under_compound_key_with_split_words():
    raw = build_raw_v2([_chapter()], _results(), CAT)
    assert "1:2:1-1:3:2" in raw and len(raw["1:2:1-1:3:2"]) == 1
    wbv = raw["1:2:1-1:3:2"][0]["words_by_verse"]
    assert set(wbv) == {"1:2", "1:3"}, "cross-verse words routed per verse, occurrence intact"
    assert "1:2" not in raw  # not collapsed to a single-verse top-level key


def test_failed_seg_recorded_not_emitted():
    raw = build_raw_v2([_chapter()], _results(), CAT)
    fails = raw["_meta"]["mfa_failures"]
    assert len(fails) == 1 and fails[0]["seg"] == 2 and fails[0]["ref"] == "1:2:1-1:2:3"


def test_word_shape_offsets_and_uid_passthrough():
    raw = build_raw_v2([_chapter()], _results(), CAT)
    w0 = raw["1:1"][1]["words_by_verse"]["1:1"][0]  # 2nd run, seg offset 2000ms, word at 2.0s
    assert len(w0) == 5 and w0[0] == 1 and w0[1] == 4000  # widx + (2.0s -> 2000ms) + 2000 offset
    assert isinstance(w0[3], list) and isinstance(w0[4], list)
    assert raw["1:2:1-1:3:2"][0]["segment_uid"] == "uid-xv"
    assert raw["1:1"][0]["segment_uid"] is None


# --- the structural guarantee ---

def test_round_trip_matches_build_outputs():
    chapter, results = _chapter(), _results()
    expected, _words, _fails = _build_outputs(copy.deepcopy(chapter), copy.deepcopy(results))
    v2 = build_raw_v2([copy.deepcopy(chapter)], copy.deepcopy(results), CAT)
    got = canonical_occurrence(v2, CAT)
    assert got == expected, "canonical_occurrence(build_raw_v2(x)) must equal build_outputs(x)"


def test_adjacent_same_verse_is_within_verse_stutter():
    # Two ADJACENT 1:1 segs are one run (contiguity) -> within-verse stutter,
    # both kept (not a re-recitation skip). Documents the _repeat_pass rule.
    got = canonical_occurrence(build_raw_v2([_chapter()], _results(), CAT), CAT)
    assert sorted(w[0] for w in got["1:1"]["words"]) == [1, 1, 2, 2]
    assert "verse_start_ms" in got["1:1"] and "verse_end_ms" in got["1:1"]


def _chapter_rerecite():
    # 1:1 take A, then 1:2 (breaks the run), then a fuller 1:1 take B.
    return {
        "ref": "1",
        "segments": [
            {"matched_ref": "1:1:1-1:1:2", "time_start": 0, "time_end": 1000},
            {"matched_ref": "1:2:1-1:2:3", "time_start": 1000, "time_end": 2000},
            {"matched_ref": "1:1:1-1:1:4", "time_start": 2000, "time_end": 3000},
        ],
    }


def _results_rerecite():
    return {0: [
        (0, _ok(["1:1:1", "1:1:2"])),                          # take A: widx 1-2
        (1, _ok(["1:2:1", "1:2:2", "1:2:3"], t0=1.0)),
        (2, _ok(["1:1:1", "1:1:2", "1:1:3", "1:1:4"], t0=2.0)),  # take B: widx 1-4 (wider, wins)
    ]}


def test_round_trip_skips_losing_rerecitation():
    chapter, results = _chapter_rerecite(), _results_rerecite()
    expected, _w, _f = _build_outputs(copy.deepcopy(chapter), copy.deepcopy(results))
    got = canonical_occurrence(
        build_raw_v2([copy.deepcopy(chapter)], copy.deepcopy(results), CAT), CAT)
    assert got == expected, "round-trip must hold through the repeat-pass skip"
    # build_raw_v2 preserves BOTH takes; the projection keeps only the wider one
    raw = build_raw_v2([chapter], results, CAT)
    assert len(raw["1:1"]) == 2, "raw preserves both re-recitation takes"
    assert sorted(w[0] for w in got["1:1"]["words"]) == [1, 2, 3, 4], "wider take B wins"


def test_round_trip_by_ayah():
    chapter = {
        "ref": "2:255",
        "segments": [
            {"matched_ref": "2:255:1-2:255:10", "time_start": 0, "time_end": 4000},
        ],
    }
    results = {0: [(0, _ok(["2:255:1", "2:255:2"]))]}
    cat = "by_ayah_audio"
    expected, _w, _f = build_outputs(
        results, None, chapters=[copy.deepcopy(chapter)],
        completed_surahs=set(), completed_refs=set(),
        refresh_surahs=None, audio_category=cat)
    v2 = build_raw_v2([copy.deepcopy(chapter)], copy.deepcopy(results), cat)
    got = canonical_occurrence(v2, cat)
    assert got == expected
