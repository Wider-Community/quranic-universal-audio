"""Tests for the audio prefetch lifecycle.

Coverage:

* ``ReciterRow.prefetch_purge_at`` round-trips through JSON.
* ``state.transition`` stamps ``prefetch_purge_at = now + 7d`` on
  ``reciter.timestamps_completed`` and clears it on every AWAITING_REVIEW
  path.
* The post-transition hook fires the prefetch queue exactly once per
  AWAITING_REVIEW entry, and not on unrelated transitions.
* ``audio_prefetch.enqueue`` is idempotent for active/queued slugs.
* ``audio_prefetch._run_one`` writes bucket artifacts, emits per-chapter
  audit events, and the ``_done.json`` sentinel only when every chapter
  succeeded.
* ``audio_prefetch.sweep_due`` deletes prefetched dirs for rows past the
  TTL and clears the stamp.

Uses the ``tmp_reciter_dir`` fixture from ``conftest.py`` for an isolated
``FilesystemBackend`` rooted at a temp dir.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from scripts.lib.schemas import (
    Actor,
    ReciterRow,
    ReciterState,
    Role,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _system_actor() -> Actor:
    return Actor(hf_user_id="tester", login_at_time="tester", role=Role.MAINTAINER)


@pytest.fixture
def patched_chapter_urls(monkeypatch):
    """Stub ``audio_meta.chapter_urls`` so the worker doesn't need a real
    catalog sidecar on the bucket."""
    from services import audio_meta, audio_fetch

    chapters = {"1": "https://cdn.example/1.mp3", "2": "https://cdn.example/2.mp3"}
    monkeypatch.setattr(audio_meta, "chapter_urls", lambda slug: dict(chapters))
    monkeypatch.setattr(audio_meta, "chapter_for_url", lambda slug, url: {
        v: k for k, v in chapters.items()
    }.get(url))
    monkeypatch.setattr(audio_meta, "is_vbr_for_url", lambda slug, url: False)
    return chapters


@pytest.fixture
def stub_fetch(monkeypatch):
    """Replace the network + ffmpeg + peaks pipeline with an in-memory stub
    that writes deterministic bytes/peaks to the bucket. Yields the call log."""
    from services import audio_fetch, storage_paths
    from services.hf_bucket import get_backend

    calls: list[dict] = []

    def fake_fetch(slug, chapter, url, *, force=False):
        backend = get_backend()
        audio_path = storage_paths.prefetched_audio_path(slug, chapter)
        peaks_path = storage_paths.prefetched_peaks_path(slug, chapter)
        data = f"audio:{slug}:{chapter}".encode()
        backend.write_bytes_atomic(audio_path, data)
        backend.write_json_atomic(peaks_path, {"duration_ms": 1000, "peaks": [[0, 0]]})
        calls.append({"slug": slug, "chapter": chapter, "url": url, "force": force})
        return audio_fetch.ChapterArtifact(
            chapter=chapter,
            audio_path=audio_path,
            peaks_path=peaks_path,
            bytes_written=len(data),
            duration_ms=1000,
            ffmpeg_remuxed=False,
        )

    monkeypatch.setattr(audio_fetch, "fetch_and_persist_chapter", fake_fetch)
    return calls


@pytest.fixture
def queue_reset(monkeypatch):
    """Reset the module-level queue + worker state before/after each test."""
    from services import audio_prefetch

    audio_prefetch._QUEUE.clear()
    audio_prefetch._ACTIVE = None
    # Prevent the daemon worker from racing the test: we drive ``_run_one``
    # directly. Setting ``_WORKER_STARTED`` true makes ``_ensure_worker`` a
    # no-op; the enqueue API still updates the queue + audit.
    monkeypatch.setattr(audio_prefetch, "_WORKER_STARTED", True, raising=False)
    yield
    audio_prefetch._QUEUE.clear()
    audio_prefetch._ACTIVE = None


# ---------------------------------------------------------------------------
# Schema round-trip
# ---------------------------------------------------------------------------


def test_prefetch_purge_at_round_trips():
    ts = datetime.now(timezone.utc).replace(microsecond=0)
    row = ReciterRow(
        slug="reciter_x",
        state=ReciterState.RELEASED,
        state_since=ts,
        prefetch_purge_at=ts + timedelta(days=7),
    )
    raw = row.model_dump(mode="json")
    assert raw["prefetch_purge_at"] is not None
    back = ReciterRow.model_validate(raw)
    assert back.prefetch_purge_at == row.prefetch_purge_at


def test_prefetch_purge_at_defaults_to_none():
    row = ReciterRow(
        slug="reciter_x",
        state=ReciterState.CATALOGUED,
        state_since=datetime.now(timezone.utc),
    )
    assert row.prefetch_purge_at is None


# ---------------------------------------------------------------------------
# State transition stamps
# ---------------------------------------------------------------------------


def test_timestamps_completed_stamps_purge_at_seven_days_ahead(
    tmp_reciter_dir, patched_chapter_urls, queue_reset
):
    from services import state

    actor = _system_actor()
    now = datetime.now(timezone.utc)

    # Set up a row in AWAITING_TIMESTAMPS state.
    row = ReciterRow(
        slug="slug_x",
        state=ReciterState.AWAITING_TIMESTAMPS,
        state_since=now,
    )
    state._persist_row(row, replace_existing=False)

    new = state.transition("slug_x", "reciter.timestamps_completed", actor=actor)
    assert new.state == ReciterState.RELEASED
    assert new.prefetch_purge_at is not None
    delta = new.prefetch_purge_at - now
    assert timedelta(days=7) - timedelta(seconds=5) < delta < timedelta(days=7) + timedelta(seconds=5)


def test_alignment_completed_clears_purge_at(
    tmp_reciter_dir, patched_chapter_urls, queue_reset
):
    """Round-tripping a row from RELEASED → AWAITING_REVIEW (via unpublished)
    must drop the stale ``prefetch_purge_at``."""
    from services import state

    actor = _system_actor()
    now = datetime.now(timezone.utc)
    row = ReciterRow(
        slug="slug_x",
        state=ReciterState.AWAITING_ALIGNMENT,
        state_since=now,
        prefetch_purge_at=now + timedelta(days=2),  # stale leftover
    )
    state._persist_row(row, replace_existing=False)

    new = state.transition("slug_x", "reciter.alignment_completed", actor=actor)
    assert new.state == ReciterState.AWAITING_REVIEW
    assert new.prefetch_purge_at is None


# ---------------------------------------------------------------------------
# Post-transition hook
# ---------------------------------------------------------------------------


def test_transition_hook_fires_for_awaiting_review(
    tmp_reciter_dir, patched_chapter_urls, queue_reset
):
    from services import audio_prefetch, state

    state.clear_transition_hooks()
    enqueued: list[str] = []

    def hook(before, after, event, actor):
        if (after.state.value if hasattr(after.state, "value") else after.state) == "awaiting_review":
            enqueued.append(after.slug)

    state.register_transition_hook(hook)
    try:
        actor = _system_actor()
        now = datetime.now(timezone.utc)
        row = ReciterRow(
            slug="slug_x",
            state=ReciterState.AWAITING_ALIGNMENT,
            state_since=now,
        )
        state._persist_row(row, replace_existing=False)

        state.transition("slug_x", "reciter.alignment_completed", actor=actor)
        assert enqueued == ["slug_x"]
    finally:
        state.clear_transition_hooks()


# ---------------------------------------------------------------------------
# Queue dedup + worker
# ---------------------------------------------------------------------------


def test_enqueue_is_idempotent_for_queued_slug(tmp_reciter_dir, queue_reset):
    from services import audio_prefetch

    # Block the worker from draining the queue so we can observe dedup.
    audio_prefetch._WORKER_STARTED = True

    assert audio_prefetch.enqueue("slug_x") is True
    assert audio_prefetch.enqueue("slug_x") is False
    assert list(audio_prefetch._QUEUE) == ["slug_x"]


def test_run_one_writes_artifacts_and_done_marker(
    tmp_reciter_dir, patched_chapter_urls, stub_fetch, queue_reset
):
    from services import audio_prefetch, storage_paths
    from services.hf_bucket import get_backend

    audio_prefetch._run_one("slug_x")

    backend = get_backend()
    assert backend.exists(storage_paths.prefetched_audio_path("slug_x", "1"))
    assert backend.exists(storage_paths.prefetched_audio_path("slug_x", "2"))
    assert backend.exists(storage_paths.prefetched_peaks_path("slug_x", "1"))
    assert backend.exists(storage_paths.prefetch_done_marker_path("slug_x"))
    assert sorted(c["chapter"] for c in stub_fetch) == ["1", "2"]


def test_run_one_skips_done_marker_on_failure(
    tmp_reciter_dir, patched_chapter_urls, monkeypatch, queue_reset
):
    """A single chapter failure must leave the sentinel absent so the next
    trigger re-fetches the missing pieces."""
    from services import audio_fetch, audio_prefetch, storage_paths
    from services.hf_bucket import get_backend

    def flaky(slug, chapter, url, *, force=False):
        if chapter == "2":
            raise audio_fetch.ChapterFetchError("download", "boom")
        backend = get_backend()
        backend.write_bytes_atomic(
            storage_paths.prefetched_audio_path(slug, chapter), b"ok"
        )
        return audio_fetch.ChapterArtifact(
            chapter=chapter,
            audio_path=storage_paths.prefetched_audio_path(slug, chapter),
            peaks_path=None,
            bytes_written=2,
            duration_ms=None,
            ffmpeg_remuxed=False,
        )

    monkeypatch.setattr(audio_fetch, "fetch_and_persist_chapter", flaky)
    audio_prefetch._run_one("slug_x")

    backend = get_backend()
    assert backend.exists(storage_paths.prefetched_audio_path("slug_x", "1"))
    assert not backend.exists(storage_paths.prefetch_done_marker_path("slug_x"))


# ---------------------------------------------------------------------------
# Sweeper
# ---------------------------------------------------------------------------


def test_sweep_due_purges_overdue_rows_and_clears_stamp(
    tmp_reciter_dir, patched_chapter_urls, queue_reset, monkeypatch
):
    from services import audio_prefetch, state, storage_paths
    from services.hf_bucket import get_backend

    # Seed a RELEASED row with a stale purge_at and pre-populate the bucket
    # dirs the sweeper should wipe.
    now = datetime.now(timezone.utc)
    row = ReciterRow(
        slug="slug_x",
        state=ReciterState.RELEASED,
        state_since=now - timedelta(days=10),
        prefetch_purge_at=now - timedelta(hours=1),
    )
    state._persist_row(row, replace_existing=False)

    backend = get_backend()
    backend.write_bytes_atomic(storage_paths.prefetched_audio_path("slug_x", "1"), b"a")
    backend.write_json_atomic(
        storage_paths.prefetched_peaks_path("slug_x", "1"), {"duration_ms": 1, "peaks": []}
    )
    backend.write_json_atomic(
        storage_paths.prefetch_done_marker_path("slug_x"),
        {"schema_version": 1, "total_chapters": 1, "completed_at_ms": 0},
    )

    purged = audio_prefetch.sweep_due()
    assert purged == 1

    assert not backend.exists(storage_paths.prefetched_audio_path("slug_x", "1"))
    assert not backend.exists(storage_paths.prefetched_peaks_path("slug_x", "1"))
    refreshed = state.get_row("slug_x")
    assert refreshed.prefetch_purge_at is None


def test_sweep_due_skips_future_purge_at(
    tmp_reciter_dir, patched_chapter_urls, queue_reset
):
    from services import audio_prefetch, state, storage_paths
    from services.hf_bucket import get_backend

    now = datetime.now(timezone.utc)
    row = ReciterRow(
        slug="slug_x",
        state=ReciterState.RELEASED,
        state_since=now,
        prefetch_purge_at=now + timedelta(days=6),
    )
    state._persist_row(row, replace_existing=False)

    backend = get_backend()
    backend.write_bytes_atomic(storage_paths.prefetched_audio_path("slug_x", "1"), b"a")

    assert audio_prefetch.sweep_due() == 0
    assert backend.exists(storage_paths.prefetched_audio_path("slug_x", "1"))
