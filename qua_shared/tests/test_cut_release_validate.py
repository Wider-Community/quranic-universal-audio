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

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import gzip  # noqa: E402

from qua_jobs import cut_release  # noqa: E402
from qua_jobs.cut_release import _verse_for_validate  # noqa: E402
from qua_shared.dataset_validation import (  # noqa: E402
    check_duration_arithmetic,
)

# An LFS pointer file — what HF auto-LFS ships for ``data/qpc_hafs.json.gz`` in
# the job image (LFS'd by extension; the Space build can't smudge it).
_LFS_POINTER = (
    b"version https://git-lfs.github.com/spec/v1\n"
    b"oid sha256:deadbeef\nsize 1452433\n"
)


def test_verse_start_zero_with_leading_word_gap():
    # verse_start_ms is a real 0; first word's audio starts at 60 ms.
    v = {"verse_start_ms": 0, "verse_end_ms": 24095,
         "words": [[1, 60, 2350], [23, 21995, 24095]]}
    out = _verse_for_validate(v, segments=[])
    assert out["verse_start_ms"] == 0          # NOT coerced to the word start (60)
    assert out["verse_end_ms"] == 24095
    assert out["duration_ms"] == 24095          # end - start, consistent
    assert check_duration_arithmetic("5:1", out) == []   # no phantom violation


def test_bounds_fall_back_to_words_when_absent():
    v = {"words": [[1, 100, 500], [2, 500, 900]]}   # no verse_start/end keys
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


def test_hash_static_refs_uses_resolved_qpc(tmp_path):
    """The manifest hashes the resolved *decompressed* qpc bytes, regardless of
    whether the staged .gz was usable."""
    (tmp_path / "surah_info.json").write_bytes(b'{"surahs": []}')
    qpc = b'{"1:1:1": "y"}'
    out = cut_release._hash_static_refs(tmp_path, qpc)
    assert out["qpc_hafs.json"]["bytes"] == len(qpc)
    assert out["qpc_hafs.json"]["sha256"] == cut_release._sha256_hex(qpc)
    assert "surah_info.json" in out
