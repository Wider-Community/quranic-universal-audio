"""Roundtrip the segment-array shard through the inspector read path.

Writes a segment-array shard gz (built by the offline writer
``qua_shared.timestamps_shards.build_segment_shards``) to
``reciters/<slug>/timestamps/<ch>.json.gz`` via the FilesystemBackend, then
reads it back through the real storage helpers and applies the consumer dedup:

  - ``data_dir.read_timestamps_chapter_gz`` returns the bucket gz **verbatim**
    (the read path is a byte pass-through — no inflate/reshape/recompress);
  - ``data_dir.read_timestamps_chapter`` is that gz inflated;
  - ``project_segment_shard`` reduces it to the canonical per-verse map.

Guards the cross-workstream contract: writer shape == storage pass-through ==
consumer dedup input, plus the dedup-correctness invariants (full coverage in
one contiguous occasion, contiguous clip, loopback retained, trailing trimmed).
"""

from __future__ import annotations

import gzip

import orjson

from qua_shared.timestamps_dedup import (
    build_raw_v2,
    confidence_by_span,
    project_segment_shard,
)
from qua_shared.timestamps_shards import build_segment_shards, gzip_shard
from services import storage_paths
from services.storage import data_dir
from services.storage.hf_bucket import get_backend

CAT = "by_surah_audio"
SLUG = "roundtrip_reciter"


def _ok(locations, t0=0.0, step=0.5):
    words = []
    for i, loc in enumerate(locations):
        s = t0 + i * step
        words.append({
            "location": loc, "start": s, "end": s + step,
            "letters": [{"char": "x", "start": s, "end": s + step}],
            "phones": [{"phone": "P", "start": s, "end": s + step}],
        })
    return {"status": "ok", "words": words}


def _write_shard(chapter_doc, results, *, cat=CAT):
    """Build a segment-array shard gz and write it at the bucket TS path.

    Returns ``(chapter, shard_doc, gz_bytes)`` for the single chapter built.
    """
    v2 = build_raw_v2([chapter_doc], results, cat)
    shards = build_segment_shards(v2, audio_category=cat, src_meta=v2.get("_meta"))
    (chapter, shard_doc), = shards.items()
    gz = gzip_shard(shard_doc)
    get_backend().write_bytes_atomic(
        storage_paths.timestamps_path_gz(SLUG, chapter), gz)
    return chapter, shard_doc, gz


def _loopback_chapter():
    # 1:1: w1-4, loop back 3-5, then trailing 4-5 (completes {1..5} at seg 1).
    chapter = {
        "ref": "1",
        "segments": [
            {"matched_ref": "1:1:1-1:1:4", "time_start": 0, "time_end": 1000},
            {"matched_ref": "1:1:3-1:1:5", "time_start": 1000, "time_end": 2000},
            {"matched_ref": "1:1:4-1:1:5", "time_start": 2000, "time_end": 3000},
        ],
    }
    results = {0: [
        (0, _ok(["1:1:1", "1:1:2", "1:1:3", "1:1:4"])),
        (1, _ok(["1:1:3", "1:1:4", "1:1:5"], t0=1.0)),
        (2, _ok(["1:1:4", "1:1:5"], t0=2.0)),
    ]}
    return chapter, results


def test_read_path_is_byte_passthrough(tmp_reciter_dir):
    chapter, _doc, gz = _write_shard(*_loopback_chapter())
    # The gz body read back is byte-identical to what the writer produced.
    assert data_dir.read_timestamps_chapter_gz(SLUG, chapter) == gz
    # The inflated form decodes to the segment-array shard shape.
    inflated = data_dir.read_timestamps_chapter(SLUG, chapter)
    shard = orjson.loads(inflated)
    assert shard["_meta"]["schema_version"] == 2
    assert isinstance(shard["segments"], list)
    assert all(set(s) == {"ref", "t", "words"} for s in shard["segments"])


def test_missing_chapter_returns_none(tmp_reciter_dir):
    assert data_dir.read_timestamps_chapter_gz(SLUG, 99) is None
    assert data_dir.read_timestamps_chapter(SLUG, 99) is None


def test_roundtrip_consumer_dedup(tmp_reciter_dir):
    chapter, _doc, _gz = _write_shard(*_loopback_chapter())
    shard = orjson.loads(data_dir.read_timestamps_chapter(SLUG, chapter))
    proj = project_segment_shard(shard)

    verse = proj["1:1"]
    widxs = [w[0] for w in verse["words"]]
    # within-pass loopback retained (the repeated 3,4); trailing seg trimmed.
    assert widxs == [1, 2, 3, 4, 3, 4, 5]
    assert set(widxs) >= {1, 2, 3, 4, 5}  # full coverage
    # audio-contiguous clip up to the completing segment (trailing 2000-3000 cut).
    assert verse["verse_start_ms"] == 0
    assert verse["verse_end_ms"] == 2000


def test_roundtrip_multi_occasion_highest_confidence(tmp_reciter_dir):
    # 1:1 take A, 1:2 interleaves, 1:1 take B — both 1:1 occasions complete.
    chapter_doc = {
        "ref": "1",
        "segments": [
            {"matched_ref": "1:1:1-1:1:3", "time_start": 0, "time_end": 1000},
            {"matched_ref": "1:2:1-1:2:2", "time_start": 1000, "time_end": 1500},
            {"matched_ref": "1:1:1-1:1:3", "time_start": 1500, "time_end": 2500},
        ],
    }
    results = {0: [
        (0, _ok(["1:1:1", "1:1:2", "1:1:3"])),
        (1, _ok(["1:2:1", "1:2:2"], t0=1.0)),
        (2, _ok(["1:1:1", "1:1:2", "1:1:3"], t0=1.5)),
    ]}
    chapter, _doc, _gz = _write_shard(chapter_doc, results)
    shard = orjson.loads(data_dir.read_timestamps_chapter(SLUG, chapter))

    detailed = {"entries": [{"ref": 1, "segments": [
        {"time_start": 0, "time_end": 1000, "confidence": 0.40},
        {"time_start": 1000, "time_end": 1500, "confidence": 0.99},
        {"time_start": 1500, "time_end": 2500, "confidence": 0.95},
    ]}]}
    proj = project_segment_shard(shard, conf_by_span=confidence_by_span(detailed))
    assert set(proj) == {"1:1", "1:2"}
    # Take B wins on confidence — one canonical contiguous occasion for 1:1.
    assert proj["1:1"]["verse_start_ms"] == 1500
    assert proj["1:1"]["verse_end_ms"] == 2500
    assert [w[0] for w in proj["1:1"]["words"]] == [1, 2, 3]
    assert [w[0] for w in proj["1:2"]["words"]] == [1, 2]
