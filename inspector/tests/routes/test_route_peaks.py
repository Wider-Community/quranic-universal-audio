"""GET /api/seg/peaks/<reciter> — slim-int8 chapter peaks route tests.

What this exercises:

- Slim packed peaks files (``<wip|published>/<slug>/peaks/<ch>.json.gz``) are
  read via ``audio_fetch.read_prefetched_peaks`` and emitted verbatim under
  ``{peaks: {<url>: {q:'int8', n, peaks_b64, bps, duration_ms}}, complete}``.
  No server-side dequant — FE inflates b64 → ``Int8Array`` once on receive.
- ``complete`` is always ``True`` (route has no background-compute path).
- Missing slim files → empty ``peaks`` dict + ``Cache-Control: no-store``.
- LRU response cache by ``(reciter, sorted_chapter_tuple)``; survives
  ``invalidate_seg_caches`` (autosave) — peaks are tied to immutable audio
  bytes, not segment edits.
- Per-URL cache + ``ThreadPoolExecutor`` fan-out — regression-tested against
  the lock-deadlock incident.
"""
from __future__ import annotations

from services.audio.peaks_slim import pack_slim


def _install_slim_peaks(backend, reciter: str, chapter: int, n_peaks: int = 60) -> None:
    """Write a synthetic slim peaks file + audio_manifest sidecar at the
    expected bucket paths. The manifest is needed because
    ``read_prefetched_peaks`` resolves URL → chapter through it; without an
    entry the reader silently returns ``None`` even with a valid slim file
    sitting next to it on the bucket.
    """
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
    # Minimal sidecar mapping the fixture's audio URL → chapter key.
    # Wire shape: {"chapters": {"<ch>": {url, ...}}}.
    backend.write_json_atomic(
        storage_paths.audio_manifest_path(reciter),
        {"chapters": {str(chapter): {"url": "https://fixture.local/audio/112.mp3"}}},
    )
    # Reset audio_meta's process-level sidecar cache so the new manifest
    # is picked up by this test run.
    from services.audio import audio_meta
    audio_meta._clear_for_test()


def test_peaks_returns_slim_int8_envelope(flask_client, tmp_reciter_dir):
    """Each URL entry carries the slim int8 envelope verbatim, never a
    nested float list. FE decodes ``peaks_b64`` → ``Int8Array`` once."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    _install_slim_peaks(tmp_reciter_dir.backend, reciter, chapter=112)

    res = flask_client.get(f"/api/seg/peaks/{reciter}?chapters=112")
    assert res.status_code == 200
    body = res.get_json()
    assert body["complete"] is True
    assert body["peaks"], "expected non-empty peaks dict"
    for url, doc in body["peaks"].items():
        assert doc["q"] == "int8"
        assert isinstance(doc["peaks_b64"], str) and doc["peaks_b64"]
        assert isinstance(doc["n"], int) and doc["n"] > 0
        assert isinstance(doc["duration_ms"], int) and doc["duration_ms"] > 0
        assert isinstance(doc["bps"], int) and doc["bps"] > 0
        assert "peaks" not in doc, "envelope must NOT carry a dequantized 'peaks' list"


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
    assert body["peaks"] == {}


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


def test_peaks_response_cache_returns_same_body_on_repeat(flask_client, tmp_reciter_dir, monkeypatch):
    """Second identical request hits the LRU cache — neither the per-URL peak
    reader nor the bucket is touched. Byte-equality alone would pass even if
    the cache were never hit (orjson is deterministic), so we positively
    assert cache presence and break the underlying reader to prove the
    second request did not re-enter it.
    """
    from services.storage.cache import get_peaks_response_cache

    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    _install_slim_peaks(tmp_reciter_dir.backend, reciter, chapter=112)

    res1 = flask_client.get(f"/api/seg/peaks/{reciter}?chapters=112&h=abc")
    assert res1.status_code == 200
    cached = get_peaks_response_cache(reciter, (112,))
    assert cached is not None, "first request should populate the LRU"

    # Sabotage the per-URL reader so any cache miss surfaces immediately.
    from services.audio import audio_fetch

    def _boom(*a, **kw):
        raise AssertionError("read_prefetched_peaks must not be reached on cache hit")

    monkeypatch.setattr(audio_fetch, "read_prefetched_peaks", _boom)

    res2 = flask_client.get(f"/api/seg/peaks/{reciter}?chapters=112&h=abc")
    assert res2.status_code == 200
    assert res1.get_data() == res2.get_data()


def test_peaks_response_cache_survives_invalidate_seg_caches(flask_client, tmp_reciter_dir):
    """``invalidate_seg_caches`` is fired from save/undo (every few seconds
    during autosave). The peaks LRU response cache MUST survive that path —
    peaks files are tied to immutable audio bytes and never change on a
    segment edit, so evicting them on save would cost a ~500ms cold miss
    every few seconds for nothing. The LRU still evicts under its own
    pressure (50-entry global cap) and on process restart.
    """
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
    cached = get_peaks_response_cache(reciter, (112,))
    assert cached is not None
    assert isinstance(cached, (bytes, bytearray))

    # Save/undo path: peaks cache MUST stay warm.
    invalidate_seg_caches(reciter)
    still_cached = get_peaks_response_cache(reciter, (112,))
    assert still_cached is not None
    assert still_cached == cached  # byte-identical, no rebuild

    # Manual cache pop is still available for explicit peaks rebuilds.
    from services.storage.cache import pop_reciter_peaks_response_cache
    pop_reciter_peaks_response_cache(reciter)
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
    returned. Healthz + other routes worked fine.
    """
    import time

    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    # Install slim peaks across multiple chapters so the ThreadPoolExecutor
    # fans out reads + cache-set calls concurrently. A single-chapter request
    # exercises a single worker and would never have reproduced the original
    # threading.Lock non-reentrant deadlock.
    chapters = (1, 2, 3, 4, 112)
    for ch in chapters:
        _install_slim_peaks(tmp_reciter_dir.backend, reciter, chapter=ch)

    chapters_csv = ",".join(str(c) for c in chapters)
    t0 = time.perf_counter()
    res = flask_client.get(f"/api/seg/peaks/{reciter}?chapters={chapters_csv}")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert res.status_code == 200, res.get_data()
    assert elapsed_ms < 2000, f"route took {elapsed_ms:.0f} ms — likely lock contention"
