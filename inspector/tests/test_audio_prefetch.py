"""Tests for the wip-audio sweeper lifecycle.

Coverage:

* ``ReciterRow.prefetch_purge_at`` round-trips through JSON.
* ``state.transition`` stamps ``prefetch_purge_at = now + 7d`` on
  ``reciter.timestamps_completed`` and clears it on every AWAITING_REVIEW
  path.
* ``audio_prefetch.sweep_due`` deletes prefetched dirs for rows past the
  TTL, deletes the sentinel, and clears the stamp.

The original test file also covered the (now-removed) per-chapter prefetch
worker — enqueue dedup, ``_run_one`` artifact writes, partial-failure done-
marker behavior, post-transition hook wiring. All gone with the worker.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.schemas import (
    Actor,
    ReciterRow,
    ReciterState,
    Role,
)


def _system_actor() -> Actor:
    return Actor(hf_user_id="tester", login_at_time="tester", role=Role.MAINTAINER)


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


def test_timestamps_completed_stamps_purge_at_seven_days_ahead(tmp_reciter_dir):
    from services import state

    actor = _system_actor()
    now = datetime.now(timezone.utc)

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


def test_alignment_completed_clears_purge_at(tmp_reciter_dir):
    """RELEASED → AWAITING_REVIEW (via alignment) must drop a stale stamp."""
    from services import state

    actor = _system_actor()
    now = datetime.now(timezone.utc)
    row = ReciterRow(
        slug="slug_x",
        state=ReciterState.AWAITING_ALIGNMENT,
        state_since=now,
        prefetch_purge_at=now + timedelta(days=2),
    )
    state._persist_row(row, replace_existing=False)

    new = state.transition("slug_x", "reciter.alignment_completed", actor=actor)
    assert new.state == ReciterState.AWAITING_REVIEW
    assert new.prefetch_purge_at is None


# ---------------------------------------------------------------------------
# Sweeper
# ---------------------------------------------------------------------------


def test_sweep_due_purges_overdue_rows_and_clears_stamp(tmp_reciter_dir):
    from services import audio_prefetch, state, storage_paths
    from services.hf_bucket import get_backend

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


def test_sweep_due_skips_future_purge_at(tmp_reciter_dir):
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
