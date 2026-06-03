"""Tests for the one-off RESHAPE transform (v2 occurrence-list → segment array).

The load-bearing assertion is CONVERGENCE: reshaping a v2 occurrence-list shard
must produce output byte-shape identical to the offline writer
(``build_segment_shards``) for the equivalent occurrence set — there is exactly
one segment-array builder and both faces must land on the same bytes.

Also covers shape classification (already-reshaped vs v2 vs v1/empty), provenance
+ ``audio_category`` carried from the shard's own ``_meta``, recitation ordering,
and rejection of compound cross-verse keys.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import gzip  # noqa: E402

import orjson  # noqa: E402
import pytest  # noqa: E402

from scripts.lib.timestamps_dedup import build_raw_v2  # noqa: E402
from scripts.lib.timestamps_reshape import (  # noqa: E402
    classify_shard,
    reshape_shard,
)
from scripts.lib.timestamps_shards import (  # noqa: E402
    build_segment_shards,
    gzip_shard,
)

CAT = "by_surah_audio"

PROVENANCE = {
    "created_at": "2026-06-04T00:00:00Z",
    "audio_source": "by_surah",
    "aligner_model": "quran_aligner_model",
    "method": "kalpy",
    "beam": 50,
    "shared_cmvn": False,
    "padding": "forward",
}


def _ok(locations, t0=0.0, step=0.5):
    """Synthetic MFA 'ok' result: one word per location, sequential times (s)."""
    words = []
    for i, loc in enumerate(locations):
        s = t0 + i * step
        words.append({
            "location": loc, "start": s, "end": s + step,
            "letters": [{"char": "x", "start": s, "end": s + step}],
            "phones": [{"phone": "P", "start": s, "end": s + step}],
        })
    return {"status": "ok", "words": words}


def _chapter_loopback():
    # 1:1 recited across two segments (loopback): words 1-2 then 3-4, then 1:2.
    return {
        "ref": "1",
        "segments": [
            {"matched_ref": "1:1:1-1:1:2", "time_start": 0, "time_end": 1000},
            {"matched_ref": "1:1:3-1:1:4", "time_start": 1500, "time_end": 2500},
            {"matched_ref": "1:2:1-1:2:3", "time_start": 2500, "time_end": 3500},
        ],
    }


def _results_loopback():
    return {0: [
        (0, _ok(["1:1:1", "1:1:2"])),
        (1, _ok(["1:1:3", "1:1:4"], t0=1.5)),
        (2, _ok(["1:2:1", "1:2:2", "1:2:3"], t0=2.5)),
    ]}


def _v2_chapter_shard(chapter, results, *, cat=CAT, meta_extra=None):
    """Build the on-bucket per-chapter v2 occurrence-list shard.

    ``build_raw_v2`` emits ``{output_key: [occ,...], "_meta": {...}}``; for a
    single chapter of single-verse refs the output keys ARE the verse keys, which
    is exactly the bucket shard shape. We stamp the shard ``_meta`` the way the
    deployed read-path stores it (schema_version 1, reciter, audio_category with
    the ``_audio`` suffix, plus provenance).
    """
    raw = build_raw_v2([chapter], results, cat)
    meta = {
        "schema_version": 1,
        "reciter": "some_reciter",
        "chapter": int(str(chapter.get("ref", "1")).split(":", 1)[0]),
        "audio_category": cat,
        "url_template": "",
        **PROVENANCE,
        **(meta_extra or {}),
    }
    shard = {"_meta": meta}
    for k, v in raw.items():
        if k == "_meta":
            continue
        shard[k] = v
    return shard


# --------------------------------------------------------------------------- #
# Convergence: reshape(v2 shard) == writer output for the same occurrence set.
# --------------------------------------------------------------------------- #


def test_reshape_converges_with_writer_segment_shape():
    chapter, results = _chapter_loopback(), _results_loopback()

    # Writer face: build the segment-array shard directly from the v2 doc.
    raw = build_raw_v2([chapter], results, CAT)
    writer_shard = build_segment_shards(
        raw, audio_category=CAT, src_meta=PROVENANCE)[1]

    # Reshape face: take the on-bucket per-chapter occurrence-list shard and
    # reshape it. Provenance lives on the shard's own _meta.
    v2_shard = _v2_chapter_shard(chapter, results)
    reshaped = reshape_shard(v2_shard)

    # Same document...
    assert reshaped == writer_shard
    # ...and byte-identical once gzipped (deterministic writer is load-bearing).
    assert gzip_shard(reshaped) == gzip_shard(writer_shard)


def test_reshape_converges_multi_verse_recitation_order():
    # Several verses, interleaved start times → both faces sort by time_start.
    chapter = {
        "ref": "2",
        "segments": [
            {"matched_ref": "2:1:1-2:1:2", "time_start": 5000, "time_end": 6000},
            {"matched_ref": "2:2:1-2:2:1", "time_start": 0, "time_end": 900},
            {"matched_ref": "2:1:3-2:1:4", "time_start": 6500, "time_end": 7200},
            {"matched_ref": "2:3:1-2:3:2", "time_start": 2000, "time_end": 3000},
        ],
    }
    results = {0: [
        (0, _ok(["2:1:1", "2:1:2"], t0=5.0)),
        (1, _ok(["2:2:1"], t0=0.0)),
        (2, _ok(["2:1:3", "2:1:4"], t0=6.5)),
        (3, _ok(["2:3:1", "2:3:2"], t0=2.0)),
    ]}
    raw = build_raw_v2([chapter], results, CAT)
    writer_shard = build_segment_shards(raw, audio_category=CAT, src_meta=PROVENANCE)[2]
    reshaped = reshape_shard(_v2_chapter_shard(chapter, results))
    assert reshaped == writer_shard
    # recitation order == ascending time_start
    starts = [s["t"][0] for s in reshaped["segments"]]
    assert starts == sorted(starts)
    refs = [s["ref"] for s in reshaped["segments"]]
    assert refs == ["2:2", "2:3", "2:1", "2:1"]


def test_reshape_by_ayah_category_normalized():
    chapter = {
        "ref": "2:255",
        "segments": [
            {"matched_ref": "2:255:1-2:255:3", "time_start": 0, "time_end": 4000},
        ],
    }
    results = {0: [(0, _ok(["2:255:1", "2:255:2", "2:255:3"]))]}
    v2_shard = _v2_chapter_shard(chapter, results, cat="by_ayah_audio")
    reshaped = reshape_shard(v2_shard)
    assert reshaped["_meta"]["audio_category"] == "by_ayah"
    assert reshaped["_meta"]["schema_version"] == 2
    assert [s["ref"] for s in reshaped["segments"]] == ["2:255"]


# --------------------------------------------------------------------------- #
# Slim _meta + word/letter/phone fidelity.
# --------------------------------------------------------------------------- #


def test_reshaped_meta_is_slim_and_drops_path_fields():
    reshaped = reshape_shard(_v2_chapter_shard(_chapter_loopback(), _results_loopback()))
    meta = reshaped["_meta"]
    assert meta["schema_version"] == 2 and meta["chapter"] == 1
    assert meta["audio_category"] == "by_surah"
    for k in ("padding", "beam", "method", "aligner_model", "shared_cmvn",
              "audio_source", "created_at"):
        assert k in meta
    # path/audio fields dropped even though the v2 shard carried them
    for k in ("reciter", "url_template", "audio_urls"):
        assert k not in meta


def test_words_letters_phones_preserved_verbatim():
    v2_shard = _v2_chapter_shard(_chapter_loopback(), _results_loopback())
    src_words = v2_shard["1:1"][0]["words_by_verse"]["1:1"]
    reshaped = reshape_shard(v2_shard)
    out_words = reshaped["segments"][0]["words"]
    assert out_words == src_words
    widx, s, e, letters, phones = out_words[0]
    assert isinstance(widx, int)
    assert len(letters[0]) == 3 and len(phones[0]) == 3


# --------------------------------------------------------------------------- #
# Classification + guard rails.
# --------------------------------------------------------------------------- #


def test_classify_v2_target_v1_empty():
    v2_shard = _v2_chapter_shard(_chapter_loopback(), _results_loopback())
    assert classify_shard(v2_shard) == "v2"

    target = reshape_shard(v2_shard)
    assert classify_shard(target) == "target"

    v1_shard = {"_meta": {"schema_version": 1}, "1:1": {"words": [[1, 0, 9]]}}
    assert classify_shard(v1_shard) == "v1"

    assert classify_shard({"_meta": {"schema_version": 2}}) == "empty"


def test_reshape_rejects_already_target():
    target = reshape_shard(_v2_chapter_shard(_chapter_loopback(), _results_loopback()))
    with pytest.raises(ValueError, match="already in the target"):
        reshape_shard(target)


def test_reshape_rejects_v1():
    v1_shard = {"_meta": {"schema_version": 1}, "1:1": {"words": [[1, 0, 9]]}}
    with pytest.raises(ValueError, match="pre-v2"):
        reshape_shard(v1_shard)


def test_reshape_rejects_compound_cross_verse():
    chapter = {
        "ref": "1",
        "segments": [
            {"matched_ref": "1:1:1-1:2:2", "time_start": 0, "time_end": 1000},
        ],
    }
    results = {0: [(0, _ok(["1:1:1", "1:2:1"]))]}
    v2_shard = _v2_chapter_shard(chapter, results)
    with pytest.raises(ValueError):
        reshape_shard(v2_shard)


def test_reshape_idempotent_via_gzip_roundtrip():
    # Reshape → gzip → inflate → still classifies as target, segments stable.
    reshaped = reshape_shard(_v2_chapter_shard(_chapter_loopback(), _results_loopback()))
    roundtrip = orjson.loads(gzip.decompress(gzip_shard(reshaped)))
    assert roundtrip == reshaped
    assert classify_shard(roundtrip) == "target"
