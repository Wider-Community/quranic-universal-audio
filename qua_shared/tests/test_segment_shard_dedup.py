"""Tests for the consumer-side segment-array projection (``project_segment_shard``).

The bucket stores every recited segment raw, in recitation order. Consumers
reduce each verse to a single canonical take via completion-based occasion
dedup. These tests exercise the rule on synthetic segment-array shards:

  - sequential split (no foreign verse) → every segment retained;
  - within-pass backward loopback → retained verbatim (never deduped);
  - full-then-trailing-redundancy → trailing post-completion segment trimmed;
  - two completing occasions → highest mean confidence wins (earliest on a tie /
    when confidence is unavailable);
  - a verse re-done after another verse interleaves → exactly one canonical take.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from qua_shared.timestamps_dedup import (  # noqa: E402
    confidence_by_span,
    project_segment_shard,
)


def _w(widx: int, s: int, e: int) -> list:
    """A word entry ``[widx, start_ms, end_ms, letters, phones]``."""
    return [widx, s, e, [], []]


def _seg(ref: str, s: int, e: int, widxs: list[int]) -> dict:
    """A segment ``{ref, t, words}`` with one word per index, evenly spaced."""
    n = len(widxs)
    span = e - s
    words = []
    for i, wi in enumerate(widxs):
        ws = s + (span * i) // max(n, 1)
        we = s + (span * (i + 1)) // max(n, 1)
        words.append(_w(wi, ws, we))
    return {"ref": ref, "t": [s, e], "words": words}


def _shard(segments: list[dict]) -> dict:
    return {"_meta": {"schema_version": 2, "chapter": 1,
                      "audio_category": "by_surah"},
            "segments": segments}


def _widxs(verse: dict) -> list[int]:
    return [w[0] for w in verse["words"]]


# --- sequential split: one occasion, every segment retained ---

def test_sequential_split_retains_all():
    shard = _shard([
        _seg("1:1", 0, 1000, [1, 2]),
        _seg("1:1", 1000, 2000, [3, 4]),
    ])
    out = project_segment_shard(shard)
    assert _widxs(out["1:1"]) == [1, 2, 3, 4]
    assert out["1:1"]["verse_start_ms"] == 0
    assert out["1:1"]["verse_end_ms"] == 2000


# --- within-pass backward loopback: retained verbatim, never deduped ---

def test_within_pass_loopback_retained_verbatim():
    # w1-4, then loops back 3-5, then 4-end: N=5; completes only at the 3rd seg.
    shard = _shard([
        _seg("1:1", 0, 1000, [1, 2, 3, 4]),
        _seg("1:1", 1000, 2000, [3, 4, 5]),
        _seg("1:1", 2000, 3000, [4, 5]),
    ])
    out = project_segment_shard(shard)
    # Coverage {1..5} first reached at the 2nd segment (adds 5); 3rd is trailing.
    assert _widxs(out["1:1"]) == [1, 2, 3, 4, 3, 4, 5]
    assert out["1:1"]["verse_end_ms"] == 2000  # trailing [4,5] seg trimmed


# --- full then a redundant trailing segment: trailing trimmed ---

def test_full_then_trailing_trimmed():
    shard = _shard([
        _seg("1:1", 0, 1000, [1, 2, 3]),   # completes {1,2,3} here
        _seg("1:1", 1000, 2000, [1, 2, 3]),  # redundant re-do of the same words
    ])
    out = project_segment_shard(shard)
    assert _widxs(out["1:1"]) == [1, 2, 3]
    assert out["1:1"]["verse_end_ms"] == 1000


# --- two completing occasions (split by a foreign verse): highest conf wins ---

def test_two_occasions_highest_confidence_wins():
    # 1:1 take A, then 1:2 (breaks the run), then 1:1 take B (also complete).
    shard = _shard([
        _seg("1:1", 0, 1000, [1, 2, 3]),       # occasion A
        _seg("1:2", 1000, 1500, [1, 2]),       # foreign — breaks the run
        _seg("1:1", 1500, 2500, [1, 2, 3]),    # occasion B
    ])
    # detailed.json confidence join: B (span 1500-2500) is higher than A.
    detailed = {"entries": [{"ref": 1, "segments": [
        {"time_start": 0, "time_end": 1000, "confidence": 0.40},
        {"time_start": 1500, "time_end": 2500, "confidence": 0.95},
        {"time_start": 1000, "time_end": 1500, "confidence": 0.99},
    ]}]}
    conf = confidence_by_span(detailed)
    out = project_segment_shard(shard, conf_by_span=conf)
    assert out["1:1"]["verse_start_ms"] == 1500  # occasion B chosen
    assert out["1:1"]["verse_end_ms"] == 2500

    # Flip confidences → occasion A now wins.
    detailed["entries"][0]["segments"][0]["confidence"] = 0.99
    detailed["entries"][0]["segments"][1]["confidence"] = 0.10
    out2 = project_segment_shard(shard, conf_by_span=confidence_by_span(detailed))
    assert out2["1:1"]["verse_start_ms"] == 0


def test_two_occasions_no_confidence_falls_back_to_earliest():
    shard = _shard([
        _seg("1:1", 0, 1000, [1, 2, 3]),
        _seg("1:2", 1000, 1500, [1, 2]),
        _seg("1:1", 1500, 2500, [1, 2, 3]),
    ])
    out = project_segment_shard(shard)  # no conf_by_span
    assert out["1:1"]["verse_start_ms"] == 0  # earliest completing occasion


# --- interleaved full re-do: exactly one canonical take across verses ---

def test_interleaved_full_redo_one_canonical_each():
    # Recitation: 1:1(A) 1:2(A) 1:1(B-redo) 1:2(B-redo). Each verse re-recited
    # after the other interleaved → two occasions per verse, one canonical.
    shard = _shard([
        _seg("1:1", 0, 1000, [1, 2]),
        _seg("1:2", 1000, 2000, [1, 2, 3]),
        _seg("1:1", 2000, 3000, [1, 2]),
        _seg("1:2", 3000, 4000, [1, 2, 3]),
    ])
    detailed = {"entries": [{"ref": 1, "segments": [
        {"time_start": 0, "time_end": 1000, "confidence": 0.5},
        {"time_start": 1000, "time_end": 2000, "confidence": 0.5},
        {"time_start": 2000, "time_end": 3000, "confidence": 0.9},  # 1:1 B wins
        {"time_start": 3000, "time_end": 4000, "confidence": 0.3},  # 1:2 A wins
    ]}]}
    out = project_segment_shard(shard, conf_by_span=confidence_by_span(detailed))
    assert set(out) == {"1:1", "1:2"}
    assert _widxs(out["1:1"]) == [1, 2] and out["1:1"]["verse_start_ms"] == 2000
    assert _widxs(out["1:2"]) == [1, 2, 3] and out["1:2"]["verse_start_ms"] == 1000


# --- by_ayah refs (single-verse chapter ref like "2:255") project the same ---

def test_by_ayah_ref_projection():
    shard = _shard([_seg("2:255", 0, 4000, [1, 2, 3])])
    out = project_segment_shard(shard)
    assert _widxs(out["2:255"]) == [1, 2, 3]
