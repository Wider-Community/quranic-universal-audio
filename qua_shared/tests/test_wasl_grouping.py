"""Waṣl-aware recitation-item grouping (``_group_verse_items``).

Pure logic — no MFA. A run of consecutive segments is ONE item when each adjacent
pair is continuous: same output verse-key (repeats/partials) OR the earlier seg
carries ``is_wasl`` (cross-verse waṣl). ``wasl_after`` records each internal
boundary's type so the aligner seeds psil only at silence boundaries and merges
the waṣl ones into one continuous phonemization.
"""

from __future__ import annotations

from qua_shared.timestamps_pipeline import _group_verse_items


def _seg(ref, t, wasl=False):
    return {"matched_ref": ref, "time_start": t, "confidence": 1, "is_wasl": wasl}


def test_cross_verse_wasl_merges_into_one_item():
    segs = [_seg("1:3:1-1:3:2", 0, wasl=True), _seg("1:4:1-1:4:3", 100)]
    items = _group_verse_items(segs)
    assert len(items) == 1
    assert items[0]["seg_idxs"] == [0, 1]
    assert items[0]["wasl_after"] == [True]


def test_same_verse_repeat_is_silence_boundary():
    # two takes of the same verse → one item, but the boundary is silence (psil).
    segs = [_seg("96:17:1-96:17:2", 0), _seg("96:17:1-96:17:2", 100)]
    items = _group_verse_items(segs)
    assert len(items) == 1
    assert items[0]["wasl_after"] == [False]


def test_retake_starts_a_new_item():
    # verse change with a stop between (not waṣl) → separate items.
    segs = [_seg("101:1:1-101:1:1", 0), _seg("101:2:1-101:2:2", 100),
            _seg("101:1:1-101:1:1", 200)]
    items = _group_verse_items(segs)
    assert [it["seg_idxs"] for it in items] == [[0], [1], [2]]
    assert all(it["wasl_after"] == [] for it in items)


def test_three_verse_wasl_chain():
    segs = [_seg("79:1:1-79:1:5", 0, wasl=True), _seg("79:2:1-79:2:5", 100, wasl=True),
            _seg("79:3:1-79:3:5", 200)]
    items = _group_verse_items(segs)
    assert len(items) == 1
    assert items[0]["seg_idxs"] == [0, 1, 2]
    assert items[0]["wasl_after"] == [True, True]


def test_split_chain_verse_in_two_groups():
    # 74-style: A -waṣl-> B[stop], then B' -waṣl-> C. B (74:40) is recited in two
    # pieces sharing the verse-key, so the run is ONE item (the internal stop is a
    # silence/psil boundary) — but the per-occurrence flags still reconstruct the
    # two waṣl groups (74:39>74:40 and 74:40>74:41), matching the live ch74 shard.
    segs = [
        _seg("74:39:1-74:39:4", 0, wasl=True), _seg("74:40:1-74:40:2", 100),
        _seg("74:40:3-74:40:3", 200, wasl=True), _seg("74:41:1-74:41:5", 300),
    ]
    items = _group_verse_items(segs)
    assert len(items) == 1
    assert items[0]["seg_idxs"] == [0, 1, 2, 3]
    assert items[0]["wasl_after"] == [True, False, True]

    # per-occurrence flag = wasl_after[j] for non-last segs, else False
    wa = items[0]["wasl_after"]
    flags = [wa[j] if j < len(wa) else False for j in range(4)]
    assert flags == [True, False, True, False]
    # FE-style walk over the flags → two waṣl groups
    groups, i = [], 0
    while i < 4:
        if flags[i]:
            j = i
            while j < 4 and flags[j]:
                j += 1
            groups.append((i, j))      # segments i..j inclusive
            i = j + 1
        else:
            i += 1
    assert groups == [(0, 1), (2, 3)]


def test_mixed_silence_then_wasl_in_one_item():
    # same-verse repeat (silence) then waṣl to the next verse → one item, mixed
    # boundary types.
    segs = [_seg("2:45:1-2:45:8", 0), _seg("2:45:6-2:45:8", 100, wasl=True),
            _seg("2:46:1-2:46:5", 200)]
    items = _group_verse_items(segs)
    assert len(items) == 1
    assert items[0]["seg_idxs"] == [0, 1, 2]
    assert items[0]["wasl_after"] == [False, True]
