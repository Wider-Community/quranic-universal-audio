"""Tests for the v2 raw timestamps extractor (occurrence-preserving)."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `from scripts.lib...` when pytest is invoked from anywhere.
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.lib.timestamps_dedup import build_raw_v2  # noqa: E402


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
            # verse 1:1 — first take
            {"matched_ref": "1:1:1-1:1:4", "time_start": 0, "time_end": 1000},
            # verse 1:1 — re-recitation (the pipeline would DROP this run)
            {"matched_ref": "1:1:1-1:1:4", "time_start": 2000, "time_end": 3000},
            # verse 1:2 — MFA failed
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


def test_repeated_verse_preserves_both_occurrences():
    raw = build_raw_v2([_chapter()], _results(), "by_surah_audio")
    assert "1:1" in raw
    occs = raw["1:1"]
    assert len(occs) == 2, "both re-recitation runs must be preserved (not deduped)"
    assert [o["seg_index"] for o in occs] == [0, 1]


def test_cross_verse_kept_under_compound_key():
    raw = build_raw_v2([_chapter()], _results(), "by_surah_audio")
    assert "1:2:1-1:3:2" in raw
    assert len(raw["1:2:1-1:3:2"]) == 1
    # the cross-verse seg is NOT collapsed into a single-verse key
    assert "1:2" not in raw  # 1:2's only seg failed; no occurrence created


def test_failed_seg_recorded_not_emitted():
    raw = build_raw_v2([_chapter()], _results(), "by_surah_audio")
    fails = raw["_meta"]["mfa_failures"]
    assert len(fails) == 1
    assert fails[0]["seg"] == 2
    assert fails[0]["ref"] == "1:2:1-1:2:3"


def test_occurrence_word_shape_and_offsets():
    raw = build_raw_v2([_chapter()], _results(), "by_surah_audio")
    occ = raw["1:1"][1]  # second run, seg time_start=2000ms
    assert occ["matched_ref"] == "1:1:1-1:1:4"
    assert occ["time_start"] == 2000 and occ["time_end"] == 3000
    w0 = occ["words"][0]
    # [widx, start_ms, end_ms, letters, phones]; word at 2.0s + 2000ms offset
    assert len(w0) == 5
    assert w0[0] == 1 and w0[1] == 4000  # widx from "1:1:1"; 2000ms (s=2.0) + 2000 offset
    assert isinstance(w0[3], list) and isinstance(w0[4], list)


def test_segment_uid_passthrough():
    raw = build_raw_v2([_chapter()], _results(), "by_surah_audio")
    assert raw["1:2:1-1:3:2"][0]["segment_uid"] == "uid-xv"
    assert raw["1:1"][0]["segment_uid"] is None  # absent on fresh extraction
