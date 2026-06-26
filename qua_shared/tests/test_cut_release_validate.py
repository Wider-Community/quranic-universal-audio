"""Regression: the cut's boundary-validation input must respect a real
``verse_start_ms == 0`` and keep its three fields consistent.

A canonical verse can legitimately start at 0 ms while its first word's audio
starts a few ms later (leading gap). The bounds the cut validates are now the
shared layout's clip window (``build_verse_layouts``), and ``_verse_for_validate``
derives ``duration_ms`` from those same bounds — so the three fields always
agree (no phantom ``duration_arithmetic``, which once aborted the cut on
``abu_bakr_al_shatri_tarteel`` 5:1). These tests run with zero pads so the clip
window equals the word-span, isolating the consistency invariant. The release's
tier bounds + letter mapping also come from the shared layout, so the GH release
and the HF dataset reconstruct the same geometry.
"""

from __future__ import annotations

import gzip
import json

import pytest

from qua_jobs import cut_release
from qua_jobs.cut_release import _verse_for_validate
from qua_shared.dataset_validation import (
    check_duration_arithmetic,
)
from qua_shared.verse_layout import build_verse_layouts, reshape_canonical

# An LFS pointer file — what HF auto-LFS ships for ``data/qpc_hafs.json.gz`` in
# the job image (LFS'd by extension; the Space build can't smudge it).
_LFS_POINTER = b"version https://git-lfs.github.com/spec/v1\noid sha256:deadbeef\nsize 1452433\n"

# Zero pads → the clip window equals the word-span, so these tier/validate tests
# read the same bounds the old word-span builder produced.
_ZERO_PADS = {"pad_start": 0, "pad_end": 0, "min_gap": 0}


def _layouts(verses: dict) -> dict:
    return build_verse_layouts(reshape_canonical(verses), **_ZERO_PADS)


def _tiers(verses: dict) -> dict:
    return cut_release._build_tier_files(
        "example_reciter", _layouts(verses), delivery_meta={"audio_category": "by_surah"}
    )


def test_verse_start_zero_with_leading_word_gap():
    # verse_start_ms is a real 0; first word's audio starts at 60 ms. With zero
    # pads the clip window is [0, 24095] — the real 0 is respected (not coerced
    # to the word start), and duration == end - start.
    verses = {"5:1": {"verse_start_ms": 0, "verse_end_ms": 24095,
                      "words": [[1, 60, 2350], [23, 21995, 24095]]}}
    out = _verse_for_validate(_layouts(verses)["5:1"])
    assert out["verse_start_ms"] == 0
    assert out["verse_end_ms"] == 24095
    assert out["duration_ms"] == 24095
    assert check_duration_arithmetic("5:1", out) == []  # no phantom violation


def test_bounds_fall_back_to_words_when_absent():
    verses = {"1:1": {"words": [[1, 100, 500], [2, 500, 900]]}}  # no verse_start/end keys
    out = _verse_for_validate(_layouts(verses)["1:1"])
    assert out["verse_start_ms"] == 100
    assert out["verse_end_ms"] == 900
    assert out["duration_ms"] == 800
    assert check_duration_arithmetic("1:1", out) == []


def test_nonzero_start_duration_consistent():
    verses = {"22:1": {"verse_start_ms": 120, "verse_end_ms": 12814, "words": [[1, 120, 12814]]}}
    out = _verse_for_validate(_layouts(verses)["22:1"])
    assert out["duration_ms"] == 12694
    assert check_duration_arithmetic("22:1", out) == []


def test_release_timestamp_tiers_preserve_verse_order():
    verses = {
        "1:1": {"words": [[1, 0, 100]]},
        "2:1": {"words": [[1, 100, 200]]},
        "10:1": {"words": [[1, 200, 300]]},
        "100:1": {"words": [[1, 300, 400]]},
    }
    files = _tiers(verses)
    for name in (
        "verse_timestamps.json.gz",
        "word_timestamps.json.gz",
        "letter_timestamps.json.gz",
    ):
        doc = json.loads(gzip.decompress(files[name]).decode("utf-8"))
        keys = [key for key in doc if key != "_meta"]
        assert keys == ["1:1", "2:1", "10:1", "100:1"]


def test_letter_tier_maps_internal_alphabet_to_external_42_set():
    # 19:1 muqattaat كٓهيعٓصٓ — internal letters carry the maddah mark; the cut
    # must emit the collapsed (maddah-free) external tokens, with timings intact.
    verses = {
        "19:1": {
            "words": [
                [
                    1,
                    0,
                    500,
                    [
                        ["كٓ", 0, 100],
                        ["ه", 100, 200],
                        ["ي", 200, 300],
                        ["عٓ", 300, 400],
                        ["صٓ", 400, 500],
                    ],
                ]
            ]
        }
    }
    files = _tiers(verses)
    doc = json.loads(gzip.decompress(files["letter_timestamps.json.gz"]).decode("utf-8"))
    letters = doc["19:1"][2]  # [[widx, char, start, end], ...]
    chars = [lt[1] for lt in letters]
    assert chars == ["ك", "ه", "ي", "ع", "ص"]  # maddah dropped
    assert all("ٓ" not in c for c in chars)
    assert letters[0] == [1, "ك", 0, 100]  # timing preserved


def test_letter_tier_fails_loud_on_unknown_token():
    # A haraka-bearing letter is not in the external alphabet → the shared layout
    # build (where the external mapping happens) aborts.
    verses = {"1:1": {"words": [[1, 0, 100, [["بَ", 0, 100]]]]}}
    with pytest.raises(ValueError):
        _layouts(verses)


def test_release_verse_bound_is_padded_clip_window():
    # Consistency with the HF dataset: the release verse bound is the padded clip
    # window [clip_start, clip_end], NOT the raw word-span. With a trailing
    # neighbour the gap is ample, so the first verse takes the full pad_end tail.
    verses = {
        "1:1": {"words": [[1, 100, 1000]], "verse_start_ms": 100, "verse_end_ms": 1000},
        "1:2": {"words": [[1, 5000, 6000]], "verse_start_ms": 5000, "verse_end_ms": 6000},
    }
    layouts = build_verse_layouts(reshape_canonical(verses), pad_start=100, pad_end=300, min_gap=100)
    files = cut_release._build_tier_files(
        "example_reciter", layouts, delivery_meta={"audio_category": "by_surah"}
    )
    verse_doc = json.loads(gzip.decompress(files["verse_timestamps.json.gz"]).decode("utf-8"))
    assert verse_doc["1:1"] == [0, 1300]  # clip window (word-span 100..1000 padded), not [100, 1000]
    # The word tier keeps the true word times (source-relative), so the word-span
    # is still recoverable from inside the padded clip.
    word_doc = json.loads(gzip.decompress(files["word_timestamps.json.gz"]).decode("utf-8"))
    assert word_doc["1:1"][1] == [[1, 100, 1000]]


# ---------------------------------------------------------------------------
# qpc_hafs byte resolution: the staged image .gz is an LFS pointer (HF
# auto-LFS by extension), so the real bytes must come from the bucket.
# Regression for ``BadGzipFile: Not a gzipped file (b've')`` aborting the cut.
# ---------------------------------------------------------------------------


def test_qpc_prefers_local_uncompressed(tmp_path):
    (tmp_path / "qpc_hafs.json").write_bytes(b'{"1:1:1": "x"}')
    assert cut_release._load_qpc_bytes(tmp_path) == b'{"1:1:1": "x"}'


def test_qpc_local_valid_gz(tmp_path):
    """CI / job staging with a real .gz and no uncompressed source."""
    raw = b'{"1:1:1": "gz"}'
    (tmp_path / "qpc_hafs.json.gz").write_bytes(gzip.compress(raw, mtime=0))
    assert cut_release._load_qpc_bytes(tmp_path) == raw


def test_qpc_lfs_pointer_gz_falls_back_to_bucket(tmp_path, monkeypatch):
    """The deployed-job case: staged .gz is an LFS pointer (not gzip), so the
    real bytes must come from the bucket's reference/qpc_hafs.json.gz."""
    raw = b'{"1:1:1": "bucket"}'
    (tmp_path / "qpc_hafs.json.gz").write_bytes(_LFS_POINTER)
    bucket = tmp_path / "bucket"
    (bucket / "reference").mkdir(parents=True)
    (bucket / cut_release.QPC_BUCKET_REL).write_bytes(gzip.compress(raw, mtime=0))
    monkeypatch.setattr(cut_release, "_bucket_root", lambda: bucket)

    assert cut_release._load_qpc_bytes(tmp_path) == raw


def test_qpc_none_when_unavailable_everywhere(tmp_path, monkeypatch):
    (tmp_path / "qpc_hafs.json.gz").write_bytes(_LFS_POINTER)
    monkeypatch.setattr(cut_release, "_bucket_root", lambda: tmp_path / "empty-bucket")

    assert cut_release._load_qpc_bytes(tmp_path) is None


def test_qpc_validation_rejects_pointer_bytes():
    with pytest.raises(RuntimeError, match="not valid QPC JSON"):
        cut_release._validate_qpc_bytes(_LFS_POINTER)


def test_qpc_validation_accepts_real_shape():
    cut_release._validate_qpc_bytes(
        b'{"1:1:1":{"id":1,"surah":"1","ayah":"1","word":"1","location":"1:1:1","text":"bismi"}}'
    )


def test_hash_static_refs_uses_resolved_qpc(tmp_path):
    """The manifest hashes the resolved *decompressed* qpc bytes, regardless of
    whether the staged .gz was usable."""
    (tmp_path / "surah_info.json").write_bytes(b'{"surahs": []}')
    qpc = b'{"1:1:1": "y"}'
    out = cut_release._hash_static_refs(tmp_path, qpc)
    assert out["qpc_hafs.json"]["bytes"] == len(qpc)
    assert out["qpc_hafs.json"]["sha256"] == cut_release._sha256_hex(qpc)
    assert "surah_info.json" in out


def test_audio_urls_come_from_sidecar_chapters():
    sidecar = {
        "schema_version": 1,
        "slug": "example_reciter",
        "_meta": {"checksum": "abc", "chapter_count": 1, "category": "by_surah"},
        "chapters": {
            "100": {
                "url": "https://cdn.example/100.mp3",
                "duration_sec": 60,
                "bitrate_mode": "cbr",
                "max_linear_seek_err_ms": 26,
            }
        },
    }

    urls, offsets = cut_release._audio_sources_from_manifest("example_reciter", sidecar)
    assert urls == {"100": "https://cdn.example/100.mp3"}
    assert offsets == {}  # CDN by-surah: no offsets


def test_audio_urls_tolerate_legacy_sidecar_metadata():
    sidecar = {
        "_meta": {"source": "intake_ingest_manual", "chapter_count": 1},
        "chapters": {
            "2": {
                "url": "https://cdn.example/2.mp3",
                "duration_sec": 8848.826,
                "max_linear_seek_err_ms": 26,
            }
        },
    }

    urls, offsets = cut_release._audio_sources_from_manifest("legacy_reciter", sidecar)
    assert urls == {"2": "https://cdn.example/2.mp3"}
    assert offsets == {}


def test_combined_source_surfaces_native_url_and_offset():
    # One Drive file serves chapters 1 + 2 (bucket path swapped into ``url``);
    # the release must point at the native ``source_url`` and carry the offset of
    # the chapter that starts partway into the file.
    sidecar = {
        "schema_version": 1,
        "slug": "combined_reciter",
        "_meta": {"checksum": "abc", "chapter_count": 2, "category": "by_surah"},
        "chapters": {
            "1": {
                "url": "https://bucket/reciters/combined_reciter/audio/1.mp3",
                "source_url": "https://drive.google.com/file/d/XYZ/view",
            },
            "2": {
                "url": "https://bucket/reciters/combined_reciter/audio/2.mp3",
                "source_url": "https://drive.google.com/file/d/XYZ/view",
                "source_offset_ms": 215000,
            },
        },
    }

    urls, offsets = cut_release._audio_sources_from_manifest("combined_reciter", sidecar)
    assert urls == {
        "1": "https://drive.google.com/file/d/XYZ/view",
        "2": "https://drive.google.com/file/d/XYZ/view",
    }
    assert offsets == {"2": 215000}  # only the non-zero offset is emitted


def test_single_file_offset_emitted_without_source_url():
    # A unique-per-chapter source whose recitation starts after a lead-in: the
    # URL is already native (no ``source_url``) but the offset must still ship.
    sidecar = {
        "_meta": {"checksum": "abc", "chapter_count": 1, "category": "by_surah"},
        "chapters": {
            "36": {
                "url": "https://drive.google.com/file/d/ABC/view",
                "source_offset_ms": 4200,
            }
        },
    }

    urls, offsets = cut_release._audio_sources_from_manifest("single_file_reciter", sidecar)
    assert urls == {"36": "https://drive.google.com/file/d/ABC/view"}
    assert offsets == {"36": 4200}


def test_empty_audio_urls_are_fatal_for_catalog_build():
    rec = {"slug": "example_reciter", "audio_category": "by_surah"}
    verses = {"100:1": {"words": [[1, 0, 100]]}}
    sidecar = {
        "schema_version": 1,
        "slug": "example_reciter",
        "_meta": {"checksum": "abc", "chapter_count": 0, "category": "by_surah"},
        "chapters": {},
    }

    with pytest.raises(RuntimeError, match="no usable audio URLs"):
        cut_release._build_catalog_json(rec, sidecar, verses)
