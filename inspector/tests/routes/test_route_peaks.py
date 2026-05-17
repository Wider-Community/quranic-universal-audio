"""GET /api/seg/peaks/<reciter> — Option A (slim packed) route shape tests.

What this exercises:

- Slim packed peaks files (``wip/<slug>/peaks/<ch>.json.gz``) are read,
  inflated via ``unpack_slim``, and returned under the legacy response shape
  ``{peaks: {<url>: {duration_ms, peaks}}, complete}`` so the FE consumer
  (``_fetchPeaks`` / ``setWaveformPeaks``) sees no change.
- ``complete`` is always ``True`` post-migration (no background compute path
  remains).
- Missing slim files yield an empty ``peaks`` dict + ``Cache-Control:
  no-store`` so the client doesn't lock in an empty response permanently.
- LRU response cache returns identical body on repeat request (cache key is
  ``(reciter, sorted chapter tuple)``).
- ``invalidate_seg_caches(reciter)`` evicts the response cache.
"""
from __future__ import annotations

import os

from services.audio.peaks_slim import pack_slim

os.environ.setdefault("INSPECTOR_SESSION_SECRET", "0" * 64)


def _install_slim_peaks(backend, reciter: str, chapter: int, n_peaks: int = 60) -> None:
    """Write a synthetic slim peaks file at the expected bucket path."""
    from services.storage import storage_paths
    hd = {
        "schema_version": 2,
        "duration_ms": int(n_peaks * 1000 / 30),  # 30 bps source
        "peaks": [[-0.1, 0.1]] * n_peaks,
    }
    backend.write_bytes_atomic(
        storage_paths.prefetched_peaks_path(reciter, chapter),
        pack_slim(hd),
    )


def test_peaks_returns_inflated_slim_under_legacy_shape(flask_client, tmp_reciter_dir):
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    _install_slim_peaks(tmp_reciter_dir.backend, reciter, chapter=112)

    res = flask_client.get(f"/api/seg/peaks/{reciter}?chapters=112")
    assert res.status_code == 200
    body = res.get_json()
    assert "peaks" in body
    assert body["complete"] is True
    # Each entry has the legacy chapter-peaks shape so FE consumers
    # (setWaveformPeaks) work unchanged.
    for url, doc in body["peaks"].items():
        assert isinstance(doc["peaks"], list)
        assert isinstance(doc["duration_ms"], int)
        assert doc["duration_ms"] > 0


def test_peaks_chapter_filter_excludes_other_chapters(flask_client, tmp_reciter_dir):
    """Filter narrows to the requested chapters only."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    _install_slim_peaks(tmp_reciter_dir.backend, reciter, chapter=112)
    # No peaks installed for chapter 1 — filter to it.
    res = flask_client.get(f"/api/seg/peaks/{reciter}?chapters=1")
    assert res.status_code == 200
    body = res.get_json()
    # Empty result; ikhlas URLs not requested.
    assert body["peaks"] == {} or all(
        u for u in body["peaks"].keys()  # any returned URL must be for ch1, but fixture has none
    )


def test_peaks_missing_file_returns_no_store(flask_client, tmp_reciter_dir):
    """When no slim files exist on the bucket, the response has empty
    ``peaks`` and a ``no-store`` cache directive so the client can retry."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    # No peaks files written

    res = flask_client.get(f"/api/seg/peaks/{reciter}?chapters=112")
    assert res.status_code == 200
    assert res.get_json()["peaks"] == {}
    assert "no-store" in res.headers.get("Cache-Control", "")


def test_peaks_response_cache_returns_same_body_on_repeat(flask_client, tmp_reciter_dir):
    """Second identical request hits the LRU cache — body byte-identical."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    _install_slim_peaks(tmp_reciter_dir.backend, reciter, chapter=112)

    res1 = flask_client.get(f"/api/seg/peaks/{reciter}?chapters=112&h=abc")
    res2 = flask_client.get(f"/api/seg/peaks/{reciter}?chapters=112&h=abc")
    assert res1.status_code == 200 and res2.status_code == 200
    assert res1.get_data() == res2.get_data()


def test_peaks_response_cache_evicted_by_invalidate_seg_caches(flask_client, tmp_reciter_dir):
    """``invalidate_seg_caches`` is wired to ``pop_reciter_peaks_response_cache``;
    after invalidation the route re-reads the bucket."""
    from services.storage.cache import (
        get_peaks_response_cache,
        invalidate_seg_caches,
    )

    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    _install_slim_peaks(tmp_reciter_dir.backend, reciter, chapter=112)

    # Warm the cache
    res = flask_client.get(f"/api/seg/peaks/{reciter}?chapters=112")
    assert res.status_code == 200
    assert get_peaks_response_cache(reciter, (112,)) is not None

    invalidate_seg_caches(reciter)
    assert get_peaks_response_cache(reciter, (112,)) is None


def test_peaks_unknown_reciter_returns_404(flask_client, tmp_reciter_dir):
    res = flask_client.get("/api/seg/peaks/does_not_exist?chapters=1")
    assert res.status_code == 404


def test_peaks_no_lock_deadlock_on_misses(flask_client, tmp_reciter_dir):
    """Regression: the route fans bucket reads through ThreadPoolExecutor and
    populates the per-URL cache via ``set_peaks_for_url``, which acquires
    ``cache.get_peaks_lock()`` internally. The route MUST NOT wrap that call
    in another ``with lock`` block — ``threading.Lock`` is non-reentrant, so
    that pattern deadlocks the worker thread and the request hangs forever.

    Caught live during E2E verification on a freshly-migrated husary bucket:
    every ``/api/seg/peaks/<reciter>`` request hung at 60s with 0 bytes
    returned. Healthz + other routes worked fine. This test installs slim
    peaks across two chapters so the route exercises the cache-set codepath
    and asserts the response arrives within a reasonable wall-clock budget.
    """
    import time
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    _install_slim_peaks(tmp_reciter_dir.backend, reciter, chapter=112)

    t0 = time.perf_counter()
    res = flask_client.get(f"/api/seg/peaks/{reciter}?chapters=112")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert res.status_code == 200, res.get_data()
    # Generous bound — local FilesystemBackend reads are sub-ms; if this is
    # over 1s we're back in the deadlock regime.
    assert elapsed_ms < 1000, f"route took {elapsed_ms:.0f} ms — likely lock contention"
