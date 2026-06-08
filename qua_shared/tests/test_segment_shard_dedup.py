"""Tests for the consumer-side segment-array projection (``project_segment_shard``).

The bucket stores every recited segment raw, in recitation order. Consumers
reduce each verse to a single canonical take via completion-based occasion
dedup. These tests exercise the rule on synthetic segment-array shards:

  - sequential split (no foreign verse) → every segment retained;
  - within-pass backward loopback → retained verbatim (never deduped);
  - full-then-trailing-redundancy → trailing post-completion segment trimmed;
  - leading false-start (restart at word 1) → redundant prefix trimmed;
  - two completing occasions → the EARLIEST (first recited) wins;
  - a verse re-done after another verse interleaves → exactly one canonical take.
"""

from __future__ import annotations

from qua_shared.timestamps_dedup import project_segment_shard, select_complete_verses


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
    return {
        "_meta": {"schema_version": 2, "chapter": 1, "audio_category": "by_surah"},
        "segments": segments,
    }


def _widxs(verse: dict) -> list[int]:
    return [w[0] for w in verse["words"]]


# --- sequential split: one occasion, every segment retained ---


def test_sequential_split_retains_all():
    shard = _shard(
        [
            _seg("1:1", 0, 1000, [1, 2]),
            _seg("1:1", 1000, 2000, [3, 4]),
        ]
    )
    out = project_segment_shard(shard)
    assert _widxs(out["1:1"]) == [1, 2, 3, 4]
    assert out["1:1"]["verse_start_ms"] == 0
    assert out["1:1"]["verse_end_ms"] == 2000


# --- within-pass backward loopback: retained verbatim, never deduped ---


def test_within_pass_loopback_retained_verbatim():
    # w1-4, then loops back 3-5, then 4-end: N=5; completes only at the 3rd seg.
    shard = _shard(
        [
            _seg("1:1", 0, 1000, [1, 2, 3, 4]),
            _seg("1:1", 1000, 2000, [3, 4, 5]),
            _seg("1:1", 2000, 3000, [4, 5]),
        ]
    )
    out = project_segment_shard(shard)
    # Coverage {1..5} first reached at the 2nd segment (adds 5); 3rd is trailing.
    assert _widxs(out["1:1"]) == [1, 2, 3, 4, 3, 4, 5]
    assert out["1:1"]["verse_end_ms"] == 2000  # trailing [4,5] seg trimmed


# --- full then a redundant trailing segment: trailing trimmed ---


def test_full_then_trailing_trimmed():
    shard = _shard(
        [
            _seg("1:1", 0, 1000, [1, 2, 3]),  # completes {1,2,3} here
            _seg("1:1", 1000, 2000, [1, 2, 3]),  # redundant re-do of the same words
        ]
    )
    out = project_segment_shard(shard)
    assert _widxs(out["1:1"]) == [1, 2, 3]
    assert out["1:1"]["verse_end_ms"] == 1000


# --- leading false-start (restart at word 1): redundant prefix trimmed ---


def test_leading_false_start_trimmed():
    # w1-3 (abandoned), then a restart at word 1 that completes {1..5}. One
    # occasion (no foreign verse). The leading 1-3 is a redundant false start.
    shard = _shard(
        [
            _seg("1:1", 0, 1000, [1, 2, 3]),
            _seg("1:1", 1000, 3000, [1, 2, 3, 4, 5]),
        ]
    )
    out = project_segment_shard(shard)
    assert _widxs(out["1:1"]) == [1, 2, 3, 4, 5]  # leading [1,2,3] dropped
    assert out["1:1"]["verse_start_ms"] == 1000  # clip starts at the restart
    assert out["1:1"]["verse_end_ms"] == 3000


def test_leading_false_start_not_trimmed_for_lookback():
    # A mid-verse lookback jumps back to word 3 (NOT word 1) — kept verbatim.
    shard = _shard(
        [
            _seg("1:1", 0, 1500, [1, 2, 3, 4, 5]),
            _seg("1:1", 1500, 3000, [3, 4, 5]),
        ]
    )
    out = project_segment_shard(shard)
    # Completes at the first segment; the trailing lookback seg is trimmed, the
    # leading pass is preserved (no restart at word 1 to trim).
    assert _widxs(out["1:1"]) == [1, 2, 3, 4, 5]
    assert out["1:1"]["verse_start_ms"] == 0


# --- two completing occasions (split by a foreign verse): earliest wins ---


def test_two_occasions_earliest_wins():
    # 1:1 take A, then 1:2 (breaks the run), then 1:1 take B (also complete).
    shard = _shard(
        [
            _seg("1:1", 0, 1000, [1, 2, 3]),  # occasion A (earliest)
            _seg("1:2", 1000, 1500, [1, 2]),  # foreign — breaks the run
            _seg("1:1", 1500, 2500, [1, 2, 3]),  # occasion B
        ]
    )
    out = project_segment_shard(shard)
    assert out["1:1"]["verse_start_ms"] == 0  # earliest completing occasion (A)
    assert out["1:1"]["verse_end_ms"] == 1000


# --- interleaved full re-do: exactly one canonical take across verses ---


def test_interleaved_full_redo_one_canonical_each():
    # Recitation: 1:1(A) 1:2(A) 1:1(B-redo) 1:2(B-redo). Each verse re-recited
    # after the other interleaved → two occasions per verse, earliest canonical.
    shard = _shard(
        [
            _seg("1:1", 0, 1000, [1, 2]),
            _seg("1:2", 1000, 2000, [1, 2, 3]),
            _seg("1:1", 2000, 3000, [1, 2]),
            _seg("1:2", 3000, 4000, [1, 2, 3]),
        ]
    )
    out = project_segment_shard(shard)
    assert set(out) == {"1:1", "1:2"}
    assert _widxs(out["1:1"]) == [1, 2] and out["1:1"]["verse_start_ms"] == 0
    assert _widxs(out["1:2"]) == [1, 2, 3] and out["1:2"]["verse_start_ms"] == 1000


# --- by_ayah refs (single-verse chapter ref like "2:255") project the same ---


def test_by_ayah_ref_projection():
    shard = _shard([_seg("2:255", 0, 4000, [1, 2, 3])])
    out = project_segment_shard(shard)
    assert _widxs(out["2:255"]) == [1, 2, 3]


# --- verse bounds are a superset of every word/letter time (no clip truncation) ---


def test_verse_bounds_cover_word_and_letter_bleed():
    # A word (and its last letter) can end a few ms PAST the segment's t[1]; the
    # clip bound must reach them, not stop at the segment edge, or the final word
    # gets truncated and a word end falls outside [verse_start, verse_end].
    seg = {
        "ref": "1:1",
        "t": [0, 1000],
        "words": [
            [1, 0, 500, [["a", 0, 500]], []],
            # word 2 ends 5 ms past seg.t[1]=1000; its last letter ends at 1007.
            [2, 500, 1005, [["b", 500, 1007]], []],
        ],
    }
    v = project_segment_shard(_shard([seg]))["1:1"]
    assert v["verse_end_ms"] == 1007 and v["verse_start_ms"] == 0, v
    # Invariant: every word + letter time lies within [verse_start, verse_end].
    for w in v["words"]:
        assert v["verse_start_ms"] <= w[1] and w[2] <= v["verse_end_ms"]
        for _ch, ls, le in w[3]:
            assert v["verse_start_ms"] <= ls and le <= v["verse_end_ms"]


# --- select_complete_verses: publish-time gate dropping incomplete verses ---


def _projected(*widxs: int) -> dict:
    """A projected canonical-take value carrying one word entry per index."""
    return {
        "words": [_w(wi, i * 10, i * 10 + 10) for i, wi in enumerate(widxs)],
        "verse_start_ms": 0,
        "verse_end_ms": len(widxs) * 10,
    }


def test_gate_drops_verse_missing_trailing_words():
    # 10-word verse recited only through word 8 → dropped.
    projected = {"1:1": _projected(1, 2, 3, 4, 5, 6, 7, 8)}
    kept, dropped = select_complete_verses(projected, {(1, 1): 10})
    assert kept == {}
    assert dropped == ["1:1"]


def test_gate_drops_verse_missing_interior_word():
    # Word 3 never recited (gap), rest present → dropped.
    projected = {"1:1": _projected(1, 2, 4, 5, 6, 7, 8, 9, 10)}
    kept, dropped = select_complete_verses(projected, {(1, 1): 10})
    assert kept == {}
    assert dropped == ["1:1"]


def test_gate_keeps_fully_covered_verse():
    projected = {"1:1": _projected(1, 2, 3, 4, 5, 6, 7, 8, 9, 10)}
    kept, dropped = select_complete_verses(projected, {(1, 1): 10})
    assert set(kept) == {"1:1"}
    assert dropped == []


def test_gate_uses_word_indices_not_count():
    # 10 word entries (a duplicated index 10) but index 3 absent → still dropped:
    # completeness is by INDEX coverage, never by len(words) >= N_ref.
    projected = {"1:1": _projected(1, 2, 4, 5, 6, 7, 8, 9, 10, 10)}
    assert len(projected["1:1"]["words"]) == 10
    kept, dropped = select_complete_verses(projected, {(1, 1): 10})
    assert kept == {}
    assert dropped == ["1:1"]


def test_gate_keeps_verse_with_unknown_reference_count():
    # No reference word count for the ref → fail-open, keep unchanged.
    projected = {"2:5": _projected(1, 2)}
    kept, dropped = select_complete_verses(projected, {(1, 1): 10})
    assert kept == {"2:5": projected["2:5"]}
    assert dropped == []


def test_gate_drops_only_incomplete_verses_in_mixed_map():
    projected = {
        "1:1": _projected(1, 2, 3),  # complete (3-word verse)
        "1:2": _projected(1, 2),  # incomplete (missing word 3)
        "1:3": _projected(1, 2, 3, 4),  # complete (4-word verse)
    }
    word_counts = {(1, 1): 3, (1, 2): 3, (1, 3): 4}
    kept, dropped = select_complete_verses(projected, word_counts)
    assert set(kept) == {"1:1", "1:3"}
    assert dropped == ["1:2"]


def test_gate_through_projection_drops_trailing_incomplete():
    # End-to-end: a shard recited only through word 8 of a 10-word verse projects
    # to a canonical take of {1..8}, which the gate then drops.
    shard = _shard([_seg("1:1", 0, 1000, [1, 2, 3, 4, 5, 6, 7, 8])])
    projected = project_segment_shard(shard)
    assert _widxs(projected["1:1"]) == [1, 2, 3, 4, 5, 6, 7, 8]
    kept, dropped = select_complete_verses(projected, {(1, 1): 10})
    assert kept == {}
    assert dropped == ["1:1"]
