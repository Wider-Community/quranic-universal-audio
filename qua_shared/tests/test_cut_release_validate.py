"""Regression: the cut's boundary-validation input must respect a real
``verse_start_ms == 0``.

A canonical verse can legitimately start at 0 ms while its first word's audio
starts a few ms later (leading gap). The old builder used
``v.get("verse_start_ms") or words[0][1]``, which treats the real ``0`` as
falsy and substitutes the word start for the *field* — while computing
``duration_ms`` from the real ``0``. That asymmetry manufactured a phantom
``duration_arithmetic`` violation and aborted the cut (seen on
``abu_bakr_al_shatri_tarteel`` 5:1 etc.). ``_verse_for_validate`` resolves the
bounds once so the three fields always agree.
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

# An LFS pointer file — what HF auto-LFS ships for ``data/qpc_hafs.json.gz`` in
# the job image (LFS'd by extension; the Space build can't smudge it).
_LFS_POINTER = b"version https://git-lfs.github.com/spec/v1\noid sha256:deadbeef\nsize 1452433\n"


def test_verse_start_zero_with_leading_word_gap():
    # verse_start_ms is a real 0; first word's audio starts at 60 ms.
    v = {"verse_start_ms": 0, "verse_end_ms": 24095, "words": [[1, 60, 2350], [23, 21995, 24095]]}
    out = _verse_for_validate(v, segments=[])
    assert out["verse_start_ms"] == 0  # NOT coerced to the word start (60)
    assert out["verse_end_ms"] == 24095
    assert out["duration_ms"] == 24095  # end - start, consistent
    assert check_duration_arithmetic("5:1", out) == []  # no phantom violation


def test_bounds_fall_back_to_words_when_absent():
    v = {"words": [[1, 100, 500], [2, 500, 900]]}  # no verse_start/end keys
    out = _verse_for_validate(v, segments=[])
    assert out["verse_start_ms"] == 100
    assert out["verse_end_ms"] == 900
    assert out["duration_ms"] == 800
    assert check_duration_arithmetic("1:1", out) == []


def test_nonzero_start_duration_consistent():
    v = {"verse_start_ms": 120, "verse_end_ms": 12814, "words": [[1, 120, 12814]]}
    out = _verse_for_validate(v, segments=[])
    assert out["duration_ms"] == 12694
    assert check_duration_arithmetic("22:1", out) == []


def test_release_timestamp_tiers_preserve_verse_order():
    verses = {
        "1:1": {"words": [[1, 0, 100]]},
        "2:1": {"words": [[1, 100, 200]]},
        "10:1": {"words": [[1, 200, 300]]},
        "100:1": {"words": [[1, 300, 400]]},
    }
    files = cut_release._build_tier_files(
        "example_reciter",
        verses,
        delivery_meta={"audio_category": "by_surah"},
    )

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
    files = cut_release._build_tier_files(
        "example_reciter", verses, delivery_meta={"audio_category": "by_surah"}
    )
    doc = json.loads(gzip.decompress(files["letter_timestamps.json.gz"]).decode("utf-8"))
    letters = doc["19:1"][2]  # [[widx, char, start, end], ...]
    chars = [lt[1] for lt in letters]
    assert chars == ["ك", "ه", "ي", "ع", "ص"]  # maddah dropped
    assert all("ٓ" not in c for c in chars)
    assert letters[0] == [1, "ك", 0, 100]  # timing preserved


def test_letter_tier_fails_loud_on_unknown_token():
    # A haraka-bearing letter is not in the external alphabet → cut aborts.
    verses = {"1:1": {"words": [[1, 0, 100, [["بَ", 0, 100]]]]}}
    with pytest.raises(ValueError):
        cut_release._build_tier_files(
            "example_reciter", verses, delivery_meta={"audio_category": "by_surah"}
        )


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

    assert cut_release._audio_urls_from_manifest("example_reciter", sidecar) == {
        "100": "https://cdn.example/100.mp3"
    }


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
