"""Tests for the temporal segment-array shard builder (build_segment_shards).

Asserts the TARGET shape: per-chapter ``{"_meta", "segments": [...]}`` where
each segment is ``{"ref": "surah:ayah", "t": [start, end], "words": [...]}``,
words keep the ``[widx, s, e, letters, phones]`` shape, segments are in
recitation order, and ``_meta`` is slim (current segment schema + chapter +
normalized audio_category + aligner provenance; no reciter / url_template /
audio_urls). RAW: every accepted occurrence is one segment entry.
"""

from __future__ import annotations

import gzip

import orjson
import pytest

from qua_shared.tests.conftest import (
    PROVENANCE as _BASE_PROVENANCE,
)
from qua_shared.tests.conftest import (
    _multi_verse_loopback,
    _multi_verse_loopback_results,
    _ok,
)
from qua_shared.timestamps_dedup import build_raw_v2
from qua_shared.timestamps_shards import (
    SEGMENT_SCHEMA_VERSION,
    build_segment_shards,
    gzip_shard,
)

CAT = "by_surah_audio"

# Extends the canonical provenance with path/audio fields the slim _meta must
# exclude (reciter / url_template / audio_urls).
PROVENANCE = {
    **_BASE_PROVENANCE,
    "reciter": "some_reciter",
    "url_template": "example.com/{surah:03d}.mp3",
    "audio_urls": {"1": "example.com/001.mp3"},
}


def _build(chapter, results, *, src_meta=PROVENANCE, cat=CAT):
    v2 = build_raw_v2([chapter], results, cat)
    return build_segment_shards(v2, audio_category=cat, src_meta=src_meta)


def test_segments_are_single_verse_recitation_ordered():
    shards = _build(_multi_verse_loopback(), _multi_verse_loopback_results())
    assert set(shards) == {1}
    segs = shards[1]["segments"]
    # 3 RAW segments (both loopback takes of 1:1 + the 1:2 seg), no dedup.
    assert [s["ref"] for s in segs] == ["1:1", "1:1", "1:2"]
    assert [s["t"] for s in segs] == [[0, 1000], [1500, 2500], [2500, 3500]]
    # every ref is a single verse "surah:ayah"
    for s in segs:
        assert s["ref"].count(":") == 1


def test_word_shape_widx_s_e_letters_phones():
    segs = _build(_multi_verse_loopback(), _multi_verse_loopback_results())[1]["segments"]
    words = segs[0]["words"]
    assert words[0][0] == 1 and words[1][0] == 2  # widx
    for w in words:
        assert len(w) == 5
        widx, s, e, letters, phones = w
        assert isinstance(widx, int) and isinstance(s, int) and isinstance(e, int)
        assert isinstance(letters, list) and letters and len(letters[0]) == 3
        assert isinstance(phones, list) and phones and len(phones[0]) == 3


def test_meta_is_slim_v2():
    meta = _build(_multi_verse_loopback(), _multi_verse_loopback_results())[1]["_meta"]
    assert meta["schema_version"] == SEGMENT_SCHEMA_VERSION
    assert meta["chapter"] == 1
    # category normalized: by_surah_audio -> by_surah
    assert meta["audio_category"] == "by_surah"
    # provenance retained when present
    for k in (
        "padding",
        "beam",
        "method",
        "aligner_model",
        "shared_cmvn",
        "audio_source",
        "created_at",
    ):
        assert k in meta
    assert meta["beam"] == 50 and meta["method"] == "kalpy"
    # excluded
    for k in ("reciter", "url_template", "audio_urls"):
        assert k not in meta


def test_by_ayah_category_normalized():
    chapter = {
        "ref": "2:255",
        "segments": [
            {"matched_ref": "2:255:1-2:255:3", "time_start": 0, "time_end": 4000},
        ],
    }
    results = {0: [(0, _ok(["2:255:1", "2:255:2", "2:255:3"]))]}
    shards = _build(chapter, results, cat="by_ayah_audio")
    assert shards[2]["_meta"]["audio_category"] == "by_ayah"
    assert [s["ref"] for s in shards[2]["segments"]] == ["2:255"]


def test_gzip_is_deterministic():
    shards = _build(_multi_verse_loopback(), _multi_verse_loopback_results())
    a = gzip_shard(shards[1])
    b = gzip_shard(shards[1])
    assert a == b
    # round-trips through gzip back to the same document
    assert orjson.loads(gzip.decompress(a)) == shards[1]


def test_compound_cross_verse_rejected():
    # A cross-verse seg yields a compound output key in build_raw_v2; the
    # builder must refuse to emit it (job blocks these upstream).
    chapter = {
        "ref": "1",
        "segments": [
            {"matched_ref": "1:1:1-1:2:2", "time_start": 0, "time_end": 1000},
        ],
    }
    results = {0: [(0, _ok(["1:1:1", "1:2:1"]))]}
    v2 = build_raw_v2([chapter], results, CAT)
    with pytest.raises(ValueError):
        build_segment_shards(v2, audio_category=CAT, src_meta=PROVENANCE)


def test_src_meta_defaults_to_v2_doc_meta():
    # When src_meta is omitted, provenance comes from the v2 doc _meta (which
    # build_raw_v2 only fills with schema_version + mfa_failures) — slim meta
    # still emits the required core fields.
    v2 = build_raw_v2([_multi_verse_loopback()], _multi_verse_loopback_results(), CAT)
    shards = build_segment_shards(v2, audio_category=CAT)
    meta = shards[1]["_meta"]
    assert meta["schema_version"] == SEGMENT_SCHEMA_VERSION and meta["chapter"] == 1
    assert meta["audio_category"] == "by_surah"
