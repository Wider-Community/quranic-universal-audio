"""Tests for the slim packed peaks format (services/audio/peaks_slim.py)."""

from __future__ import annotations

import gzip

import numpy as np
import pytest

from services.audio.peaks_slim import (
    PEAKS_SLIM_BPS,
    SLIM_SCHEMA_VERSION,
    _decimate,
    pack_slim,
    unpack_slim,
)


def _hd_doc(n_peaks: int, duration_ms: int | None = None) -> dict:
    """Build a synthetic HD-shape peaks dict at PEAKS_BUCKETS_PER_SEC=30."""
    rng = np.random.default_rng(seed=42)
    # min ∈ [-1, 0], max ∈ [0, 1] — realistic envelope shape
    mn = rng.uniform(-1.0, 0.0, n_peaks).astype(np.float32)
    mx = rng.uniform(0.0, 1.0, n_peaks).astype(np.float32)
    return {
        "schema_version": 2,
        "duration_ms": duration_ms if duration_ms is not None else int(n_peaks * 1000 / 30),
        "peaks": np.stack([mn, mx], axis=1).tolist(),
    }


def test_pack_unpack_round_trip_preserves_duration_and_count():
    hd = _hd_doc(300)  # 10 seconds at 30 bps
    blob = pack_slim(hd)
    slim = unpack_slim(blob)
    assert slim is not None
    assert slim["schema_version"] == SLIM_SCHEMA_VERSION
    assert slim["duration_ms"] == hd["duration_ms"]
    assert slim["bps"] == PEAKS_SLIM_BPS
    # 300 input peaks @ 30bps -> 100 output peaks @ 10bps (3x decimation)
    assert len(slim["peaks"]) == 100


def test_unpack_returns_list_of_lists_for_slicer_compat():
    """`_slice_chapter_peaks` in routes/segments/peaks.py expects `peaks` to
    be `list` and each entry to be subscriptable as [min, max]. unpack_slim
    must satisfy this — numpy arrays would slip past isinstance(_, list).
    """
    slim = unpack_slim(pack_slim(_hd_doc(120)))
    assert isinstance(slim["peaks"], list)
    assert all(isinstance(p, list) and len(p) == 2 for p in slim["peaks"])


def test_quantization_envelope_preserved():
    """Loud transients (max ≈ 1.0, min ≈ -1.0) must survive decimate + int8.
    Slim peaks shouldn't show silence where the source had a transient."""
    n = 90  # 3 seconds at 30 bps → 30 peaks at 10 bps
    peaks = [[-0.001, 0.001]] * n  # quiet baseline
    # Inject a loud transient mid-stream
    peaks[45] = [-0.95, 0.95]
    hd = {"schema_version": 2, "duration_ms": 3000, "peaks": peaks}
    slim = unpack_slim(pack_slim(hd))
    assert slim is not None
    # The transient at peaks[45] lands in bucket 45 // 3 = 15 of the slim output
    bucket = slim["peaks"][15]
    # Quantization tolerance: 1/127 ~= 0.008
    assert bucket[0] < -0.9, f"loud min lost: {bucket[0]}"
    assert bucket[1] > 0.9, f"loud max lost: {bucket[1]}"


def test_decimate_handles_non_divisible_tail():
    """30 input peaks @ 30bps cleanly → 10 output @ 10bps. But 32 input peaks
    leaves a 2-peak tail; the tail should fold into a final bucket rather
    than being dropped."""
    arr = np.arange(64, dtype=np.float32).reshape(32, 2) / 64.0  # 32 peaks
    out = _decimate(arr, src_bps=30, dst_bps=10)
    # 32 // 3 = 10 full buckets + 2-peak tail folded into 1 extra = 11 buckets
    assert len(out) == 11


def test_decimate_no_op_when_dst_ge_src():
    arr = np.array([[0.1, 0.2], [-0.3, 0.4]], dtype=np.float32)
    np.testing.assert_array_equal(_decimate(arr, 30, 30), arr)
    np.testing.assert_array_equal(_decimate(arr, 30, 60), arr)


def test_pack_emits_valid_gzip_member():
    """The route concatenates multiple pack_slim outputs; each one must be a
    self-contained gzip member so `gzip.decompress(a + b)` reads both."""
    blob_a = pack_slim(_hd_doc(60))
    blob_b = pack_slim(_hd_doc(90))
    # gzip module reads concatenated members natively (RFC 1952)
    combined = gzip.decompress(blob_a + blob_b)
    # Two JSON documents glued back-to-back — each starts with `{` and ends with `}`
    assert combined.count(b"{") >= 2
    assert combined.count(b"}") >= 2


def test_pack_byte_identical_for_same_input():
    """mtime=0 in gzip header — same input produces byte-identical output so
    CDN/browser cache keys stay stable across re-bakes that don't change
    the payload."""
    hd = _hd_doc(60)
    assert pack_slim(hd) == pack_slim(hd)


def test_unpack_returns_none_on_garbage():
    assert unpack_slim(b"") is None
    assert unpack_slim(b"not gzip") is None
    assert unpack_slim(gzip.compress(b"{not json")) is None


def test_unpack_returns_none_on_wrong_schema_version():
    """Pre-v3 files (v1/v2 float-JSON) must not slip through as v3 dicts.
    Reader catches them and returns None so the cache miss re-bakes."""
    fake_v2 = gzip.compress(b'{"schema_version":2,"duration_ms":1000,"peaks":[[0,0]]}')
    assert unpack_slim(fake_v2) is None


def test_pack_rejects_malformed_input():
    with pytest.raises(ValueError):
        pack_slim({"duration_ms": 1000})  # missing 'peaks'
    with pytest.raises(ValueError):
        pack_slim({"peaks": [[0, 0]]})  # missing 'duration_ms'
    with pytest.raises(ValueError):
        pack_slim({"duration_ms": 1000, "peaks": [1, 2, 3]})  # wrong shape (1D)
