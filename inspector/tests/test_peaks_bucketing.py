"""Bucket coverage in ``services.peaks._bucket_pcm_minmax``.

Pre-v2 bucketing computed ``block_size = num_samples // num_buckets`` and
broke when ``num_samples`` wasn't divisible by ``num_buckets``: the tail
samples weren't bucketed, so the peaks array fell short of the
``duration_ms`` it advertised, and the FE's
``i = peaks.length * t / duration_ms`` mapping silently stretched the
timeline (~0.25 % on long chapters → ~2 s drift at minute 15 →
mis-registered silences on the husary 3:28:25-3:29:10 sakt).

These tests pin the v2 contract: the bucketer covers every sample, even
on awkward sample/bucket ratios, and emits ``schema_version: 2`` on its
public dicts so read sites can lazily invalidate v1 entries.
"""
from __future__ import annotations

import struct

from config import PEAKS_FFMPEG_SAMPLE_RATE, PEAKS_SCHEMA_VERSION
from services.peaks import (_bucket_pcm_minmax, compute_audio_peaks,
                            compute_segment_peaks, is_current_schema)


def test_bucketer_covers_every_sample_when_not_divisible():
    # num_samples=1000, num_buckets=33 → integer-divide v1 left 1000-33*30 = 10 samples
    # dropped at the tail; v2 must place a non-empty bucket at the end.
    samples = list(range(1000))
    buckets = _bucket_pcm_minmax(samples, num_samples=1000, num_buckets=33)
    assert len(buckets) == 33
    # The last bucket's max must reflect the file's tail samples (>= 970/32768).
    last_max = buckets[-1][1] * 32768
    assert last_max >= 970, f"last bucket max {last_max} suggests tail samples were dropped"


def test_bucketer_covers_every_sample_when_divisible():
    samples = list(range(1000))
    buckets = _bucket_pcm_minmax(samples, num_samples=1000, num_buckets=100)
    assert len(buckets) == 100
    # Each bucket spans exactly 10 samples; bucket i's max is sample (i+1)*10-1.
    # The bucketer rounds float amplitudes to 4 dp, which can ±1 the recovered
    # integer at very small values, so assert proportional ordering rather than
    # exact equality.
    first_max = buckets[0][1] * 32768
    last_max = buckets[-1][1] * 32768
    assert 8 <= first_max <= 11        # ~9
    assert 998 <= last_max <= 1000     # ~999
    # Bucket maxes must be monotonically non-decreasing on a monotonic input.
    for i in range(1, 100):
        assert buckets[i][1] >= buckets[i - 1][1]


def test_bucketer_handles_short_inputs():
    # Fewer samples than buckets → degenerate buckets collapse, output truncates.
    samples = [100, -100, 50]
    buckets = _bucket_pcm_minmax(samples, num_samples=3, num_buckets=10)
    assert 0 < len(buckets) <= 3


def test_bucketer_edge_cases():
    assert _bucket_pcm_minmax([], 0, 10) == []
    assert _bucket_pcm_minmax([1, 2, 3], 3, 0) == []


def test_compute_audio_peaks_drift_was_zeroed_out():
    """End-to-end probe of the fencepost using a synthetic decode result.

    Stubs the ffmpeg call so the test stays hermetic. With a stride that
    doesn't divide cleanly (55_106_240 samples / 206_648 buckets, the
    husary ch 3 shape), v1 dropped 137_872 samples (~17 s); v2 must
    bucket all of them.
    """
    import services.audio.peaks as peaks_mod

    num_samples = 55_106_240  # ≈6888.3 sec * 8000 Hz
    # Synthesize a raw PCM byte stream where the last 1000 samples are
    # peak-loud and earlier samples are quiet. Pre-v2 dropped the tail, so
    # the peaks max would stay quiet. Post-v2, the last bucket must capture
    # the loud tail.
    loud_tail = 1000
    samples = [0] * (num_samples - loud_tail) + [30_000] * loud_tail
    raw = struct.pack(f"<{num_samples}h", *samples)

    class _R:
        returncode = 0
        stdout = raw

    peaks_mod.subprocess.run = lambda *a, **k: _R()  # type: ignore[attr-defined]
    try:
        out = compute_audio_peaks("/fake/path.mp3")
    finally:
        # `subprocess.run` was monkey-patched on the module; reload the
        # default by re-importing the subprocess attribute from stdlib.
        import subprocess as _sp
        peaks_mod.subprocess = _sp  # type: ignore[attr-defined]

    assert out is not None
    assert out["schema_version"] == PEAKS_SCHEMA_VERSION
    assert is_current_schema(out)

    expected_duration_ms = int(num_samples / PEAKS_FFMPEG_SAMPLE_RATE * 1000)
    assert out["duration_ms"] == expected_duration_ms
    assert len(out["peaks"]) > 0
    # Last bucket must reflect the loud tail (v1 would still be near zero).
    last_max = out["peaks"][-1][1]
    assert last_max > 0.5, (
        f"last bucket max={last_max} -- tail samples appear to have been "
        f"dropped, the v1 fencepost has regressed"
    )


def test_compute_segment_peaks_emits_v2_schema(monkeypatch, tmp_path):
    """`compute_segment_peaks` must label its results with the current
    schema so disk-cache / covering-cache reads can lazily invalidate v1
    entries."""
    import services.audio.audio_source as audio_source
    import services.audio.peaks as peaks_mod

    # Hermetic decode -- 8000 samples → 1 sec, peaks_per_sec=30 ⇒ 10 buckets.
    pcm = struct.pack("<8000h", *([5000] * 8000))

    monkeypatch.setattr(peaks_mod, "peaks_cache_path",
                        lambda r, k: tmp_path / "p.json")
    monkeypatch.setattr(audio_source, "resolve",
                        lambda r, u: audio_source.AudioSource(
                            cdn_url=u, data=b"\x00\x00", path=None,
                            vbr=False, bitrate_kbps=None, chapter_key="1"))
    monkeypatch.setattr(peaks_mod, "_ffmpeg_decode_segment",
                        lambda src, url, s, d: pcm)

    out = compute_segment_peaks("https://cdn/x.mp3", 0, 1000, "r", chapter=1)
    assert out is not None
    assert is_current_schema(out)
    assert out["schema_version"] == PEAKS_SCHEMA_VERSION


def test_is_current_schema_rejects_pre_v2():
    """Read sites use ``is_current_schema`` to fall through stale entries."""
    assert is_current_schema(None) is False
    assert is_current_schema({}) is False
    assert is_current_schema({"duration_ms": 10, "peaks": []}) is False  # v1
    assert is_current_schema({"schema_version": 1, "peaks": []}) is False
    assert is_current_schema({"schema_version": PEAKS_SCHEMA_VERSION,
                              "duration_ms": 10, "peaks": []}) is True
