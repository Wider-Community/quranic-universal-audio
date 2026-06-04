"""Tests for the ``job_status`` log-persistence backstop.

The in-container job self-writes its terminal record WITHOUT logs; the backstop
in ``job_status`` must backfill the captured log tail onto a logless terminal
record (the original bug: logs only persisted while the record read
running/unknown, so successful runs never saved logs → empty history).
"""
from __future__ import annotations

import sys
import types

import pytest

from services.admin import timestamps_jobs


class _Stage:
    def __init__(self, stage):
        self.stage = stage


class _Info:
    def __init__(self, stage):
        self.status = _Stage(stage)


@pytest.fixture
def fake_hf(monkeypatch):
    """Stub huggingface_hub.inspect_job / fetch_job_logs (imported inside
    ``job_status``). Returns a handle to set the reported stage + log lines."""
    state = {"stage": "succeeded", "logs": ["line1", "line2"]}
    mod = types.ModuleType("huggingface_hub")
    mod.inspect_job = lambda job_id: _Info(state["stage"])
    mod.fetch_job_logs = lambda job_id: list(state["logs"])
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)
    return state


def test_backstop_backfills_logs_on_logless_succeeded_record(fake_hf, monkeypatch):
    # Job self-wrote a terminal record but with no logs (the bug case).
    existing = {"job_id": "j1", "slug": "r", "type": "ts",
                "status": "succeeded", "started_at": "t0", "ended_at": "t1",
                "logs": []}
    monkeypatch.setattr(timestamps_jobs, "read_job_record", lambda slug, jid: dict(existing))
    written = {}
    monkeypatch.setattr(timestamps_jobs, "_write_job_record",
                        lambda rec: written.update(rec.model_dump(exclude_none=True)))

    out = timestamps_jobs.job_status("r", "j1")

    assert out["status"] == "succeeded"
    assert out["logs"] == ["line1", "line2"]
    # The persisted record gained logs but kept its terminal status + ended_at.
    assert written["logs"] == ["line1", "line2"]
    assert written["status"] == "succeeded"
    assert written["ended_at"] == "t1"


def test_backstop_noop_when_record_already_has_logs(fake_hf, monkeypatch):
    existing = {"job_id": "j1", "slug": "r", "type": "ts",
                "status": "succeeded", "logs": ["old"]}
    monkeypatch.setattr(timestamps_jobs, "read_job_record", lambda slug, jid: dict(existing))
    writes = []
    monkeypatch.setattr(timestamps_jobs, "_write_job_record", lambda rec: writes.append(rec))

    timestamps_jobs.job_status("r", "j1")

    assert writes == []  # nothing changed → no rewrite


def test_backstop_sets_terminal_status_on_running_record(fake_hf, monkeypatch):
    fake_hf["stage"] = "failed"
    existing = {"job_id": "j1", "slug": "r", "type": "ts", "status": "running",
                "started_at": "t0", "logs": []}
    monkeypatch.setattr(timestamps_jobs, "read_job_record", lambda slug, jid: dict(existing))
    written = {}
    monkeypatch.setattr(timestamps_jobs, "_write_job_record",
                        lambda rec: written.update(rec.model_dump(exclude_none=True)))

    out = timestamps_jobs.job_status("r", "j1")

    assert out["status"] == "failed"
    assert written["status"] == "failed"
    assert written["logs"] == ["line1", "line2"]
    assert written.get("ended_at")  # backfilled


# ---------------------------------------------------------------------------
# complete_timestamps_job — auto-release orchestrator
# ---------------------------------------------------------------------------


def _seed_marked_ready(slug: str = "rec_a") -> None:
    """Seed an under_review reciter with an open, marked-ready claim."""
    from tests.conftest import _seed_state

    _seed_state(slug, state="under_review", assignee_hf_id="u-rev",
                marked_ready=True)


def test_complete_publishes_marked_ready(monkeypatch):
    from services.state import state as state_service

    _seed_marked_ready("rec_a")
    monkeypatch.setattr(timestamps_jobs, "_has_any_shard", lambda slug: True)

    out = timestamps_jobs.complete_timestamps_job("rec_a", "job-1")

    assert out["released"] is True
    assert out["state"] == "released"
    row = state_service.get_row("rec_a")
    assert row.state.value == "released"
    assert row.assignee_hf_id is None
    assert row.timestamps_job_ids == ["job-1"]


def _seed_released_with_ledger(slug: str, *, ts_version: str, hf_version: str | None = None) -> None:
    """Seed a released reciter with a current ``ts`` (and optional ``hf``)
    per_recitation_releases row — the post-first-publish shape a regen acts on."""
    from datetime import datetime, timezone

    from services import db
    from services.db import repo_releases
    from tests.conftest import _seed_state

    _seed_state(slug, state="released")
    now = datetime.now(timezone.utc)
    with db.transaction():
        repo_releases.insert_per_recitation_release(
            track="ts", slug=slug, version=ts_version, produced_at=now,
            produced_by="SYSTEM_ACTOR", produced_by_job_id=ts_version,
        )
        if hf_version is not None:
            repo_releases.insert_per_recitation_release(
                track="hf", slug=slug, version=hf_version, produced_at=now,
                produced_by="SYSTEM_ACTOR",
            )


def test_complete_regen_idempotent_when_ts_already_recorded(monkeypatch):
    """A poll re-fire of an already-recorded job (released + the job's ts row
    present) is a no-op — no duplicate ts row, no extra audit event."""
    from services.db import repo_releases

    _seed_released_with_ledger("rec_a", ts_version="job-1")
    monkeypatch.setattr(timestamps_jobs, "_has_any_shard", lambda slug: True)

    out = timestamps_jobs.complete_timestamps_job("rec_a", "job-1")

    assert out["released"] is False
    assert out["reason"] == "ts already recorded"
    # Still exactly one current ts row at the original version.
    assert repo_releases.current_release("ts", "rec_a")["version"] == "job-1"


def test_complete_regen_on_released_row(monkeypatch):
    """A fresh TS run (new job_id) on a released reciter: no transition, new ts
    row supersedes the prior, HF release stamped stale, ts_regenerated audited."""
    from services.db import repo_releases, repo_transitions
    from services.state import state as state_service

    _seed_released_with_ledger("rec_a", ts_version="job-old", hf_version="sha-old")
    monkeypatch.setattr(timestamps_jobs, "_has_any_shard", lambda slug: True)

    out = timestamps_jobs.complete_timestamps_job("rec_a", "job-new")

    assert out["released"] is False
    assert out["regenerated"] is True
    # State unchanged — no released → released transition.
    assert state_service.get_row("rec_a").state.value == "released"
    # New ts row is current; the prior one is superseded.
    assert repo_releases.current_release("ts", "rec_a")["version"] == "job-new"
    assert repo_releases.release_by_version("ts", "rec_a", "job-old")["superseded_at"] is not None
    # HF membership stamped stale so the operator is driven to re-publish.
    assert repo_releases.current_release("hf", "rec_a")["stale_since"] is not None
    # Audit trail carries the distinct regen event.
    events = [r for r in repo_transitions.for_slug("rec_a")
              if r["event"] == "reciter.ts_regenerated"]
    assert len(events) == 1
    assert events[0]["payload"]["job_id"] == "job-new"


def test_complete_regen_refuses_when_no_shards(monkeypatch):
    """A regen job that exits 0 without writing shards records nothing."""
    from services.db import repo_releases

    _seed_released_with_ledger("rec_a", ts_version="job-old")
    monkeypatch.setattr(timestamps_jobs, "_has_any_shard", lambda slug: False)

    out = timestamps_jobs.complete_timestamps_job("rec_a", "job-new")

    assert out["released"] is False
    assert out["reason"] == "no shards"
    # No new ts row — the prior remains current.
    assert repo_releases.current_release("ts", "rec_a")["version"] == "job-old"


def test_complete_noop_when_not_marked_ready(monkeypatch):
    from services.state import state as state_service
    from tests.conftest import _seed_state

    _seed_state("rec_a", state="under_review", assignee_hf_id="u-rev")
    monkeypatch.setattr(timestamps_jobs, "_has_any_shard", lambda slug: True)

    out = timestamps_jobs.complete_timestamps_job("rec_a", "job-1")

    assert out["released"] is False
    # Pin the reason discriminator so a regression that takes a different
    # noop branch (e.g. ``no shards``) doesn't silently masquerade as this
    # one — the other noop tests assert their reason already.
    assert out["reason"] == "not marked-ready / wrong state"
    assert state_service.get_row("rec_a").state.value == "under_review"


def test_complete_refuses_when_no_shards(monkeypatch):
    from services.state import state as state_service

    _seed_marked_ready("rec_a")
    monkeypatch.setattr(timestamps_jobs, "_has_any_shard", lambda slug: False)

    out = timestamps_jobs.complete_timestamps_job("rec_a", "job-1")

    assert out["released"] is False
    assert out["reason"] == "no shards"
    assert state_service.get_row("rec_a").state.value == "under_review"


def test_complete_is_idempotent_on_double_call(monkeypatch):
    from services.state import state as state_service

    _seed_marked_ready("rec_a")
    monkeypatch.setattr(timestamps_jobs, "_has_any_shard", lambda slug: True)

    first = timestamps_jobs.complete_timestamps_job("rec_a", "job-1")
    second = timestamps_jobs.complete_timestamps_job("rec_a", "job-1")

    assert first["released"] is True
    assert second["released"] is False  # already released → no-op
    assert state_service.get_row("rec_a").state.value == "released"


def test_complete_unknown_slug_is_noop():
    out = timestamps_jobs.complete_timestamps_job("nope", "job-1")
    assert out["released"] is False
    assert out["reason"] == "unknown slug"
    # state must be None for unknown slugs — pin so a regression that
    # synthesizes a phantom state can't slip through.
    assert out["state"] is None


# ---------------------------------------------------------------------------
# Job-completion notification dot (delivery_states.last_job_finished_at)
# ---------------------------------------------------------------------------


def _count(hf_user_id: str = "admin") -> int:
    from services.db import repo_review_views

    return repo_review_views.count_unviewed_for_user(hf_user_id)


def _view(slug: str, hf_user_id: str = "admin") -> None:
    from services.admin import reviews as reviews_service

    reviews_service.mark_viewed(slug, caller_hf_id=hf_user_id)


def test_marked_ready_lights_the_dot():
    _seed_marked_ready("rec_a")
    assert _count() == 1  # marked-ready, never viewed (existing behavior)


def test_success_relights_dot_after_view(monkeypatch):
    """A finished job is a fresh event even after the admin viewed the
    marked-ready row — success publishes and re-lights on the Published row."""
    _seed_marked_ready("rec_a")
    monkeypatch.setattr(timestamps_jobs, "_has_any_shard", lambda slug: True)
    _view("rec_a")
    assert _count() == 0

    out = timestamps_jobs.complete_timestamps_job("rec_a", "job-1")
    assert out["released"] is True
    assert _count() == 1  # job-finished, unviewed since release

    _view("rec_a")
    assert _count() == 0


def test_failure_relights_dot_without_state_change():
    from services.state import state as state_service

    _seed_marked_ready("rec_a")
    _view("rec_a")
    assert _count() == 0

    timestamps_jobs.note_timestamps_job_failed("rec_a")
    assert state_service.get_row("rec_a").state.value == "under_review"  # no publish
    assert _count() == 1  # failure lights the Marked-ready dot
