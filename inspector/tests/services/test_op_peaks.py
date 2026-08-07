"""Tests for ``services/audio/op_peaks.py`` — the save-time history-peaks
record builder (slices baked chapter peaks) — plus the dedup-by-op_id
behaviour of ``append_peaks_records``.
"""

from __future__ import annotations

import base64

import numpy as np

from services.audio import op_peaks
from services.audio.peaks_history import (
    append_peaks_records,
    load_peaks_records,
    normalize_audio_url,
)
from services.storage import cache


def _envelope(n: int, duration_ms: int, bps: int = 10) -> dict:
    """A synthetic slim int8 envelope (what ``read_prefetched_peaks`` returns).

    Bucket i holds (min=-i, max=+i) clipped to int8 so the slice is easy to
    assert on.
    """
    i8 = np.zeros((n, 2), dtype=np.int8)
    for i in range(n):
        i8[i, 0] = max(-127, -i)
        i8[i, 1] = min(127, i)
    return {
        "schema_version": 3,
        "duration_ms": duration_ms,
        "bps": bps,
        "q": "int8",
        "n": n,
        "peaks_b64": base64.b64encode(i8.tobytes()).decode("ascii"),
    }


def _unreachable(*_args, **_kwargs):
    raise AssertionError("audio_fetch.read_prefetched_peaks must not be reached")


# -- op_time_range / resolve_op_url -------------------------------------


def test_op_time_range_spans_all_snapshots():
    op = {
        "targets_before": [{"time_start": 1000, "time_end": 2000}],
        "targets_after": [
            {"time_start": 1000, "time_end": 1500},
            {"time_start": 1500, "time_end": 2200},
        ],
    }
    assert op_peaks.op_time_range(op) == (1000, 2200)


def test_op_time_range_delete_uses_before_snapshot():
    """A delete op carries only ``targets_before`` — still yields a range."""
    op = {"targets_before": [{"time_start": 500, "time_end": 900}], "targets_after": []}
    assert op_peaks.op_time_range(op) == (500, 900)


def test_op_time_range_none_when_no_times():
    assert op_peaks.op_time_range({"targets_before": [{"audio_url": "x"}]}) is None


def test_resolve_op_url_prefers_snapshot():
    op = {"targets_before": [{"audio_url": "https://cdn/3.mp3", "chapter": 3}]}
    assert op_peaks.resolve_op_url(op, {3: "https://cat/3.mp3"}) == "https://cdn/3.mp3"


def test_resolve_op_url_falls_back_to_catalog():
    op = {"targets_before": [{"chapter": 3, "time_start": 0, "time_end": 1}]}
    assert op_peaks.resolve_op_url(op, {3: "https://cat/3.mp3"}) == "https://cat/3.mp3"


def test_resolve_op_url_uses_default_chapter():
    op = {"targets_before": [{"time_start": 0, "time_end": 1}]}
    assert (
        op_peaks.resolve_op_url(op, {7: "https://cat/7.mp3"}, default_chapter=7)
        == "https://cat/7.mp3"
    )


# -- slice_slim_envelope ------------------------------------------------


def test_slice_slim_envelope_matches_the_fetching_wrapper(monkeypatch):
    """The pure slicer returns exactly what ``slice_chapter_peaks_b64``
    returns for the same envelope bytes."""
    env = _envelope(n=100, duration_ms=10_000, bps=10)
    monkeypatch.setattr(op_peaks.audio_fetch, "read_prefetched_peaks", lambda r, u: env)

    assert op_peaks.slice_slim_envelope(env, 2000, 3000) == op_peaks.slice_chapter_peaks_b64(
        "recit", "https://cdn/1.mp3", 2000, 3000
    )


def test_slice_slim_envelope_none_when_range_is_empty():
    env = _envelope(n=100, duration_ms=10_000, bps=10)
    assert op_peaks.slice_slim_envelope(env, 3000, 3000) is None


# -- slice_chapter_peaks_b64 --------------------------------------------


def test_slice_chapter_peaks_b64_round_trip(monkeypatch):
    # 100 buckets over 10_000 ms → 10 bps, 1 bucket / 100 ms.
    env = _envelope(n=100, duration_ms=10_000, bps=10)
    monkeypatch.setattr(op_peaks.audio_fetch, "read_prefetched_peaks", lambda r, u: env)

    out = op_peaks.slice_chapter_peaks_b64("recit", "https://cdn/1.mp3", 2000, 3000)
    assert out is not None
    b64, bps, start_ms, end_ms = out
    assert bps == 10
    # 2000..3000 ms at 1 bucket/100ms → buckets [20, 30) = 10 buckets.
    decoded = np.frombuffer(base64.b64decode(b64), dtype=np.int8).reshape(-1, 2)
    assert decoded.shape == (10, 2)
    # Bucket 20 had min=-20, max=20.
    assert decoded[0, 0] == -20 and decoded[0, 1] == 20
    assert start_ms == 2000 and end_ms == 3000


def test_slice_chapter_peaks_b64_none_when_unbaked(monkeypatch):
    monkeypatch.setattr(op_peaks.audio_fetch, "read_prefetched_peaks", lambda r, u: None)
    assert op_peaks.slice_chapter_peaks_b64("recit", "https://cdn/1.mp3", 0, 1000) is None


# -- build_op_records ----------------------------------------------------


def test_build_op_records_skips_unsliceable(monkeypatch):
    env = _envelope(n=100, duration_ms=10_000, bps=10)
    monkeypatch.setattr(op_peaks.audio_fetch, "read_prefetched_peaks", lambda r, u: env)
    ops = [
        {  # good
            "op_id": "op-good",
            "targets_before": [
                {"audio_url": "https://cdn/1.mp3", "time_start": 1000, "time_end": 2000}
            ],
        },
        {"op_id": "op-no-range", "targets_before": [{"audio_url": "https://cdn/1.mp3"}]},  # skip
        {
            "targets_before": [
                {"audio_url": "https://cdn/1.mp3", "time_start": 0, "time_end": 1000}
            ]
        },  # no op_id → skip
    ]
    recs = op_peaks.build_op_records("recit", ops, {})
    assert [r["op_id"] for r in recs] == ["op-good"]
    assert recs[0]["bps"] == 10 and recs[0]["peaks_b64"]


def test_build_op_records_injected_provider_never_reads_the_bucket(monkeypatch):
    """A caller holding envelopes in memory bypasses ``audio_fetch`` entirely
    — the peaks it slices are not in the bucket yet."""
    monkeypatch.setattr(op_peaks.audio_fetch, "read_prefetched_peaks", _unreachable)
    env = _envelope(n=100, duration_ms=10_000, bps=10)
    ops = [
        {
            "op_id": "op-mem",
            "targets_before": [
                {"audio_url": "https://cdn/1.mp3", "time_start": 1000, "time_end": 2000}
            ],
        }
    ]

    recs = op_peaks.build_op_records("recit", ops, {}, env_provider={"https://cdn/1.mp3": env}.get)
    assert [r["op_id"] for r in recs] == ["op-mem"]
    assert recs[0]["url"] == "https://cdn/1.mp3"


def test_build_op_records_queries_the_provider_with_the_raw_url(monkeypatch):
    """A proxy-wrapped ``audio_url`` reaches the provider verbatim, so a
    provider keyed by that same raw string hits. Only the emitted record's
    ``url`` is normalised."""
    monkeypatch.setattr(op_peaks.audio_fetch, "read_prefetched_peaks", _unreachable)
    proxy_url = "/api/seg/audio-proxy/recit?url=https%3A%2F%2Fcdn%2F1.mp3"
    envs = {proxy_url: _envelope(n=100, duration_ms=10_000, bps=10)}
    asked: list[str] = []

    def _provider(url: str) -> dict | None:
        asked.append(url)
        return envs.get(url)

    ops = [
        {
            "op_id": "op-proxy",
            "targets_before": [{"audio_url": proxy_url, "time_start": 1000, "time_end": 2000}],
        }
    ]

    recs = op_peaks.build_op_records("recit", ops, {}, env_provider=_provider)
    assert asked == [proxy_url]
    assert [r["op_id"] for r in recs] == ["op-proxy"]
    assert recs[0]["url"] == normalize_audio_url(proxy_url) == "https://cdn/1.mp3"


# -- append_peaks_records dedup -----------------------------------------


def test_append_peaks_records_dedups_by_op_id(tmp_reciter_dir):
    reciter = "dedup_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    rec = {
        "op_id": "op-1",
        "url": "https://cdn/1.mp3",
        "start_ms": 1000,
        "end_ms": 2000,
        "bps": 10,
        "peaks_b64": base64.b64encode(bytes([0, 1, 2, 3])).decode("ascii"),
    }
    assert append_peaks_records(reciter, [rec]) == 1
    # Repeat write of the same op_id is a no-op (dedup).
    assert append_peaks_records(reciter, [dict(rec)]) == 0
    persisted = [r for r in load_peaks_records(reciter) if r.get("op_id") == "op-1"]
    assert len(persisted) == 1


# -- cache invalidation --------------------------------------------------


def test_append_pops_response_cache(tmp_reciter_dir):
    """A write invalidates the serialized GET response so the next reader
    re-serializes the updated record list."""
    reciter = "append_invalidates_cache"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    cache.set_seg_history_peaks_response(reciter, b'{"records":[]}')
    rec = {
        "op_id": "op-resp",
        "url": "https://cdn/1.mp3",
        "start_ms": 0,
        "end_ms": 1000,
        "bps": 10,
        "peaks_b64": base64.b64encode(bytes([0, 1, 2, 3])).decode("ascii"),
    }
    assert append_peaks_records(reciter, [rec]) == 1
    assert cache.get_seg_history_peaks_response(reciter) is None


def test_append_dedup_skip_does_not_pop_response_cache(tmp_reciter_dir):
    """A fully-deduped write (nothing written) leaves the cached response
    intact — no spurious invalidation."""
    reciter = "dedup_preserves_cache"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    rec = {
        "op_id": "op-resp2",
        "url": "https://cdn/1.mp3",
        "start_ms": 0,
        "end_ms": 1000,
        "bps": 10,
        "peaks_b64": base64.b64encode(bytes([0, 1, 2, 3])).decode("ascii"),
    }
    append_peaks_records(reciter, [rec])
    cache.set_seg_history_peaks_response(reciter, b"sentinel")
    assert append_peaks_records(reciter, [dict(rec)]) == 0  # dedup → no write
    assert cache.get_seg_history_peaks_response(reciter) == b"sentinel"


def test_seg_invalidation_helpers_pop_response_cache():
    """Save (``pop_seg_caches_affected_by_segment_edit``) and the broad
    ``invalidate_seg_caches`` both drop the history-peaks response cache, so
    a save/undo never serves a stale serialized response."""
    reciter = "inv_reciter"
    cache.set_seg_history_peaks_response(reciter, b"x")
    cache.pop_seg_caches_affected_by_segment_edit(reciter)
    assert cache.get_seg_history_peaks_response(reciter) is None
    cache.set_seg_history_peaks_response(reciter, b"x")
    cache.invalidate_seg_caches(reciter)
    assert cache.get_seg_history_peaks_response(reciter) is None
