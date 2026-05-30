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


def test_complete_noop_when_already_released(monkeypatch):
    from tests.conftest import _seed_state

    _seed_state("rec_a", state="released")
    monkeypatch.setattr(timestamps_jobs, "_has_any_shard", lambda slug: True)

    out = timestamps_jobs.complete_timestamps_job("rec_a", "job-1")

    assert out["released"] is False
    assert out["reason"] == "already released"


def test_complete_noop_when_not_marked_ready(monkeypatch):
    from services.state import state as state_service
    from tests.conftest import _seed_state

    _seed_state("rec_a", state="under_review", assignee_hf_id="u-rev")
    monkeypatch.setattr(timestamps_jobs, "_has_any_shard", lambda slug: True)

    out = timestamps_jobs.complete_timestamps_job("rec_a", "job-1")

    assert out["released"] is False
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
