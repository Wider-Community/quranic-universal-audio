"""Publish row-building: the clip-edge convention (Change B + pad/ratio).

Locks the dataset contract: internal segment boundaries are byte-exact with the
post-MFA word ends; the two outer segments absorb the lead/tail headroom; and
adjacent verse rows always keep >= min_gap of silence (pads scale by ratio when
the inter-verse silence is tight).
"""
from __future__ import annotations

from qua_jobs.publish_hf import _fit_boundary, build_rows

SURAH = {"112": {"verses": [{"verse": 1}, {"verse": 2}]}}


def _ts(verse_words):
    return {
        "words": [[w, s, e] for (w, s, e) in verse_words],
        "letters": [(w, []) for (w, _, _) in verse_words],
        "verse_start_ms": verse_words[0][1],
        "verse_end_ms": max(e for *_, e in verse_words),
    }


def _detailed(segments):
    return {"segments": [
        {"matched_ref": mref, "matched_text": txt, "time_start": ts, "time_end": te}
        for (mref, txt, ts, te) in segments
    ]}


def test_fit_boundary_ratio_and_min_gap():
    assert _fit_boundary(1000, 2000, 300, 100, 100) == (300.0, 100.0)  # fits as-is
    tail, lead = _fit_boundary(1000, 1300, 300, 100, 100)              # overflow
    assert (tail, lead) == (150.0, 50.0)
    assert tail / lead == 3.0                       # pad_end:pad_start ratio kept
    assert (1300 - 1000) - (tail + lead) == 100     # leftover gap == min_gap
    assert _fit_boundary(1000, 1050, 300, 100, 100) == (0.0, 0.0)      # tighter than min_gap


def _rows(v1_words, v2_words, v1_segs, v2_segs):
    timestamps = {"112:1": _ts(v1_words), "112:2": _ts(v2_words)}
    detailed = {"112:1": _detailed(v1_segs), "112:2": _detailed(v2_segs)}
    return build_rows(timestamps, detailed, SURAH, {}, None,
                      pad_start=100, pad_end=300, min_gap=100)


def test_segments_byte_exact_and_outer_headroom():
    rows = _rows(
        v1_words=[(1, 1000, 1100), (2, 1200, 1300), (3, 2000, 2100), (4, 2200, 2400)],
        v2_words=[(1, 3000, 3100), (2, 3200, 3300)],
        v1_segs=[("112:1:1-112:1:2", "a", 900, 1400), ("112:1:3-112:1:4", "b", 1900, 2500)],
        v2_segs=[("112:2:1-112:2:2", "c", 2900, 3400)],
    )
    r0 = rows[0]
    # clip: first verse, no prev -> lead pad 100; next verse far -> tail pad 300
    assert r0["clip_start"] == 900 and r0["clip_end"] == 2700
    duration = r0["clip_end"] - r0["clip_start"]
    segs = r0["segments"]
    # outer segments absorb the pads
    assert segs[0][2] == 0 and segs[-1][3] == duration
    # internal boundary is byte-exact with the abutting word ends (clip-relative)
    w = {wi: (s, e) for wi, s, e in r0["word_timestamps"]}
    assert segs[0][3] == w[2][1]      # seg0 end == word2 end
    assert segs[1][2] == w[3][0]      # seg1 start == word3 start
    # the inter-segment gap is the recovered silence (word2.end -> word3.start)
    assert segs[1][2] - segs[0][3] == w[3][0] - w[2][1] > 0
    # first word sits pad_start into the clip (the intentional outer mismatch)
    assert w[1][0] == 100


def test_adjacent_rows_keep_min_gap_when_tight():
    # verse 2 starts only 300ms after verse 1 ends -> pads overflow, ratio-fit
    rows = _rows(
        v1_words=[(1, 1000, 2400)],
        v2_words=[(1, 2700, 3300)],
        v1_segs=[("112:1:1-112:1:1", "a", 900, 2500)],
        v2_segs=[("112:2:1-112:2:1", "c", 2600, 3400)],
    )
    r0, r1 = rows[0], rows[1]
    # boundary silence 300 < 500 want -> tail 150 / lead 50, gap == min_gap 100
    assert r0["clip_end"] == 2400 + 150
    assert r1["clip_start"] == 2700 - 50
    assert r1["clip_start"] - r0["clip_end"] == 100
