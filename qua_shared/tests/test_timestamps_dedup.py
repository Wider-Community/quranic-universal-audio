"""End-to-end roundtrip for the segment-array timestamps pipeline.

Exercises the whole chain on synthetic MFA results, the way the offline writer
and a release consumer compose:

    build_raw_v2 -> build_segment_shards -> gzip_shard
        -> gzip.decompress (== the inspector read-path pass-through body)
        -> project_segment_shard (consumer dedup)

The pass-through is byte-identity (``read_timestamps_chapter_gz`` returns the
bucket gz verbatim and ``read_timestamps_chapter`` just inflates it), so
decompressing the writer's gz here reproduces exactly what a consumer reads.
An inspector-side test (``inspector/tests/services/test_ts_roundtrip.py``) goes
through the real storage backend.

Asserts the dedup-correctness invariants from
``docs/planning/ts-segment-array-migration.md``:
  (a) no schema mismatch (shard shape survives gzip → inflate → project);
  (b) every verse reaches full word coverage in one contiguous occasion;
  (c) audio-contiguous canonical clip bounds (one ``[start, end]`` span);
  (d) within-pass loopbacks retained verbatim (never deduped);
  (e) trailing post-completion redundancy trimmed.
"""

from __future__ import annotations

import gzip

import orjson

from qua_shared.tests.conftest import _ok
from qua_shared.timestamps_dedup import (
    build_raw_v2,
    confidence_by_span,
    project_segment_shard,
)
from qua_shared.timestamps_shards import (
    build_segment_shards,
    gzip_shard,
)

CAT = "by_surah_audio"


def _roundtrip(chapter, results, *, cat=CAT, conf_by_span=None):
    """Full chain: raw v2 → segment shards → gz → inflate → consumer dedup.

    Returns ``(shard_doc, projected)`` for the single chapter under test, where
    ``shard_doc`` is the shape recovered after gzip → inflate (proving the
    pass-through is byte-faithful) and ``projected`` is the canonical verse map.
    """
    v2 = build_raw_v2([chapter], results, cat)
    shards = build_segment_shards(v2, audio_category=cat, src_meta=v2.get("_meta"))
    assert len(shards) == 1, "fixtures use a single chapter"
    ((_ch, shard_doc),) = shards.items()

    # Writer gz == bucket gz == wire body (read path is a byte pass-through).
    inflated = orjson.loads(gzip.decompress(gzip_shard(shard_doc)))
    assert inflated == shard_doc, "(a) shard survives gzip → inflate unchanged"

    projected = project_segment_shard(inflated, conf_by_span=conf_by_span)
    return inflated, projected


def _widxs(verse: dict) -> list[int]:
    return [w[0] for w in verse["words"]]


# --- the shard shape itself (schema-mismatch guard) ---


def test_inflated_shard_is_segment_array():
    chapter = {
        "ref": "1",
        "segments": [
            {"matched_ref": "1:1:1-1:1:3", "time_start": 0, "time_end": 1000},
        ],
    }
    results = {0: [(0, _ok(["1:1:1", "1:1:2", "1:1:3"]))]}
    shard, _proj = _roundtrip(chapter, results)
    assert shard["_meta"]["schema_version"] == 3
    assert isinstance(shard["segments"], list)
    seg = shard["segments"][0]
    assert set(seg) == {"ref", "t", "words"}
    assert seg["ref"] == "1:1" and seg["t"] == [0, 1000]
    assert all(len(w) == 5 for w in seg["words"])  # [widx, s, e, letters, phones]


# --- (b) full coverage in one contiguous occasion + (c) contiguous clip ---


def test_sequential_full_coverage_one_occasion():
    # 1:1 recited in two adjacent segments: words 1-2 then 3-4. One occasion.
    chapter = {
        "ref": "1",
        "segments": [
            {"matched_ref": "1:1:1-1:1:2", "time_start": 0, "time_end": 1000},
            {"matched_ref": "1:1:3-1:1:4", "time_start": 1000, "time_end": 2000},
        ],
    }
    results = {
        0: [
            (0, _ok(["1:1:1", "1:1:2"])),
            (1, _ok(["1:1:3", "1:1:4"], t0=1.0)),
        ]
    }
    _shard, proj = _roundtrip(chapter, results)
    assert _widxs(proj["1:1"]) == [1, 2, 3, 4], "(b) full {1..4} coverage"
    # (c) one contiguous [start, end] clip spanning both segments.
    assert proj["1:1"]["verse_start_ms"] == 0
    assert proj["1:1"]["verse_end_ms"] == 2000


# --- (d) within-pass loopback retained verbatim ---


def test_within_pass_loopback_retained():
    # w1-4, then loops back to 3-5, then 4-5: completes {1..5} at the 2nd seg;
    # the 3rd is trailing. All within one occasion (no foreign verse).
    chapter = {
        "ref": "1",
        "segments": [
            {"matched_ref": "1:1:1-1:1:4", "time_start": 0, "time_end": 1000},
            {"matched_ref": "1:1:3-1:1:5", "time_start": 1000, "time_end": 2000},
            {"matched_ref": "1:1:4-1:1:5", "time_start": 2000, "time_end": 3000},
        ],
    }
    results = {
        0: [
            (0, _ok(["1:1:1", "1:1:2", "1:1:3", "1:1:4"])),
            (1, _ok(["1:1:3", "1:1:4", "1:1:5"], t0=1.0)),
            (2, _ok(["1:1:4", "1:1:5"], t0=2.0)),
        ]
    }
    _shard, proj = _roundtrip(chapter, results)
    # (d) loopback words (the repeated 3,4) kept; (e) trailing [4,5] seg trimmed.
    assert _widxs(proj["1:1"]) == [1, 2, 3, 4, 3, 4, 5]
    assert proj["1:1"]["verse_end_ms"] == 2000  # trailing seg dropped


# --- (e) trailing post-completion redundancy trimmed ---


def test_trailing_redundant_redo_trimmed():
    # 1:1 completes {1,2,3}, then a redundant full re-do in the same occasion.
    chapter = {
        "ref": "1",
        "segments": [
            {"matched_ref": "1:1:1-1:1:3", "time_start": 0, "time_end": 1000},
            {"matched_ref": "1:1:1-1:1:3", "time_start": 1000, "time_end": 2000},
        ],
    }
    results = {
        0: [
            (0, _ok(["1:1:1", "1:1:2", "1:1:3"])),
            (1, _ok(["1:1:1", "1:1:2", "1:1:3"], t0=1.0)),
        ]
    }
    _shard, proj = _roundtrip(chapter, results)
    assert _widxs(proj["1:1"]) == [1, 2, 3]
    assert proj["1:1"]["verse_end_ms"] == 1000  # (e) trailing re-do trimmed


# --- multi-occasion: interleaved re-do → one canonical take, highest conf ---


def test_two_occasions_highest_confidence_wins():
    # 1:1 take A, then 1:2 (breaks the run), then 1:1 take B (both complete).
    chapter = {
        "ref": "1",
        "segments": [
            {"matched_ref": "1:1:1-1:1:3", "time_start": 0, "time_end": 1000},
            {"matched_ref": "1:2:1-1:2:2", "time_start": 1000, "time_end": 1500},
            {"matched_ref": "1:1:1-1:1:3", "time_start": 1500, "time_end": 2500},
        ],
    }
    results = {
        0: [
            (0, _ok(["1:1:1", "1:1:2", "1:1:3"])),
            (1, _ok(["1:2:1", "1:2:2"], t0=1.0)),
            (2, _ok(["1:1:1", "1:1:2", "1:1:3"], t0=1.5)),
        ]
    }
    # detailed.json confidence join: take B (1500-2500) beats take A (0-1000).
    detailed = {
        "entries": [
            {
                "ref": 1,
                "segments": [
                    {"time_start": 0, "time_end": 1000, "confidence": 0.40},
                    {"time_start": 1000, "time_end": 1500, "confidence": 0.99},
                    {"time_start": 1500, "time_end": 2500, "confidence": 0.95},
                ],
            }
        ]
    }
    _shard, proj = _roundtrip(chapter, results, conf_by_span=confidence_by_span(detailed))
    assert set(proj) == {"1:1", "1:2"}
    # 1:1 canonical = take B (one contiguous occasion); 1:2 = its only take.
    assert proj["1:1"]["verse_start_ms"] == 1500
    assert proj["1:1"]["verse_end_ms"] == 2500
    assert _widxs(proj["1:1"]) == [1, 2, 3]
    assert _widxs(proj["1:2"]) == [1, 2]


def test_two_occasions_no_confidence_falls_back_to_earliest():
    chapter = {
        "ref": "1",
        "segments": [
            {"matched_ref": "1:1:1-1:1:3", "time_start": 0, "time_end": 1000},
            {"matched_ref": "1:2:1-1:2:2", "time_start": 1000, "time_end": 1500},
            {"matched_ref": "1:1:1-1:1:3", "time_start": 1500, "time_end": 2500},
        ],
    }
    results = {
        0: [
            (0, _ok(["1:1:1", "1:1:2", "1:1:3"])),
            (1, _ok(["1:2:1", "1:2:2"], t0=1.0)),
            (2, _ok(["1:1:1", "1:1:2", "1:1:3"], t0=1.5)),
        ]
    }
    _shard, proj = _roundtrip(chapter, results)  # no confidence
    assert proj["1:1"]["verse_start_ms"] == 0  # earliest completing occasion


# --- by_ayah chapter ref ("2:255") projects the same way ---


def test_by_ayah_roundtrip():
    chapter = {
        "ref": "2:255",
        "segments": [
            {"matched_ref": "2:255:1-2:255:3", "time_start": 0, "time_end": 4000},
        ],
    }
    results = {0: [(0, _ok(["2:255:1", "2:255:2", "2:255:3"]))]}
    shard, proj = _roundtrip(chapter, results, cat="by_ayah_audio")
    assert shard["_meta"]["audio_category"] == "by_ayah"
    assert shard["segments"][0]["ref"] == "2:255"
    assert _widxs(proj["2:255"]) == [1, 2, 3]
