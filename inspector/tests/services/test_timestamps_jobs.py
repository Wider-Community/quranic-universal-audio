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
    monkeypatch.setattr(timestamps_jobs, "read_job_record", lambda jid: dict(existing))
    written = {}
    monkeypatch.setattr(timestamps_jobs, "_write_job_record",
                        lambda rec: written.update(rec.model_dump(exclude_none=True)))

    out = timestamps_jobs.job_status("j1")

    assert out["status"] == "succeeded"
    assert out["logs"] == ["line1", "line2"]
    # The persisted record gained logs but kept its terminal status + ended_at.
    assert written["logs"] == ["line1", "line2"]
    assert written["status"] == "succeeded"
    assert written["ended_at"] == "t1"


def test_backstop_noop_when_record_already_has_logs(fake_hf, monkeypatch):
    existing = {"job_id": "j1", "slug": "r", "type": "ts",
                "status": "succeeded", "logs": ["old"]}
    monkeypatch.setattr(timestamps_jobs, "read_job_record", lambda jid: dict(existing))
    writes = []
    monkeypatch.setattr(timestamps_jobs, "_write_job_record", lambda rec: writes.append(rec))

    timestamps_jobs.job_status("j1")

    assert writes == []  # nothing changed → no rewrite


def test_backstop_sets_terminal_status_on_running_record(fake_hf, monkeypatch):
    fake_hf["stage"] = "failed"
    existing = {"job_id": "j1", "slug": "r", "type": "ts", "status": "running",
                "started_at": "t0", "logs": []}
    monkeypatch.setattr(timestamps_jobs, "read_job_record", lambda jid: dict(existing))
    written = {}
    monkeypatch.setattr(timestamps_jobs, "_write_job_record",
                        lambda rec: written.update(rec.model_dump(exclude_none=True)))

    out = timestamps_jobs.job_status("j1")

    assert out["status"] == "failed"
    assert written["status"] == "failed"
    assert written["logs"] == ["line1", "line2"]
    assert written.get("ended_at")  # backfilled
