"""Tests for the ``job_status`` log-persistence backstop.

The in-container job self-writes its terminal record WITHOUT logs; the backstop
in ``job_status`` must backfill the captured log tail onto a logless terminal
record (the original bug: logs only persisted while the record read
running/unknown, so successful runs never saved logs → empty history).
"""

from __future__ import annotations

import sys
import types
from datetime import UTC
from typing import Any

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
    mod: Any = types.ModuleType("huggingface_hub")
    mod.inspect_job = lambda job_id: _Info(state["stage"])
    mod.fetch_job_logs = lambda job_id: list(state["logs"])
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)
    return state


def test_backstop_backfills_logs_on_logless_succeeded_record(fake_hf, monkeypatch):
    # Job self-wrote a terminal record but with no logs (the bug case).
    existing = {
        "job_id": "j1",
        "slug": "r",
        "type": "ts",
        "status": "succeeded",
        "started_at": "t0",
        "ended_at": "t1",
        "logs": [],
    }
    monkeypatch.setattr(timestamps_jobs, "read_job_record", lambda slug, jid: dict(existing))
    written = {}
    monkeypatch.setattr(
        timestamps_jobs,
        "_write_job_record",
        lambda rec: written.update(rec.model_dump(exclude_none=True)),
    )

    out = timestamps_jobs.job_status("r", "j1")

    assert out["status"] == "succeeded"
    assert out["logs"] == ["line1", "line2"]
    # The persisted record gained logs but kept its terminal status + ended_at.
    assert written["logs"] == ["line1", "line2"]
    assert written["status"] == "succeeded"
    assert written["ended_at"] == "t1"


def test_backstop_noop_when_record_already_has_logs(fake_hf, monkeypatch):
    existing = {"job_id": "j1", "slug": "r", "type": "ts", "status": "succeeded", "logs": ["old"]}
    monkeypatch.setattr(timestamps_jobs, "read_job_record", lambda slug, jid: dict(existing))
    writes = []
    monkeypatch.setattr(timestamps_jobs, "_write_job_record", lambda rec: writes.append(rec))

    timestamps_jobs.job_status("r", "j1")

    assert writes == []  # nothing changed → no rewrite


def test_backstop_sets_terminal_status_on_running_record(fake_hf, monkeypatch):
    fake_hf["stage"] = "failed"
    existing = {
        "job_id": "j1",
        "slug": "r",
        "type": "ts",
        "status": "running",
        "started_at": "t0",
        "logs": [],
    }
    monkeypatch.setattr(timestamps_jobs, "read_job_record", lambda slug, jid: dict(existing))
    written = {}
    monkeypatch.setattr(
        timestamps_jobs,
        "_write_job_record",
        lambda rec: written.update(rec.model_dump(exclude_none=True)),
    )

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

    _seed_state(slug, state="under_review", assignee_hf_id="u-rev", marked_ready=True)


def test_complete_publishes_marked_ready(monkeypatch):
    from services.state import state as state_service

    _seed_marked_ready("rec_a")
    monkeypatch.setattr(timestamps_jobs, "_has_any_shard", lambda slug: True)

    out = timestamps_jobs.complete_timestamps_job("rec_a", "job-1")

    assert out["released"] is True
    assert out["state"] == "released"
    row = state_service.get_row("rec_a")
    assert row is not None
    assert row.state.value == "released"
    assert row.assignee_hf_id is None
    assert row.timestamps_job_ids == ["job-1"]


def _seed_released_with_ledger(
    slug: str, *, ts_version: str, hf_version: str | None = None
) -> None:
    """Seed a released reciter with a current ``ts`` (and optional ``hf``)
    per_recitation_releases row — the post-first-publish shape a regen acts on."""
    from datetime import datetime, timezone

    from services import db
    from services.db import repo_releases
    from tests.conftest import _seed_state

    _seed_state(slug, state="released")
    now = datetime.now(UTC)
    with db.transaction():
        repo_releases.insert_per_recitation_release(
            track="ts",
            slug=slug,
            version=ts_version,
            produced_at=now,
            produced_by="SYSTEM_ACTOR",
            produced_by_job_id=ts_version,
        )
        if hf_version is not None:
            repo_releases.insert_per_recitation_release(
                track="hf",
                slug=slug,
                version=hf_version,
                produced_at=now,
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
    ts_current = repo_releases.current_release("ts", "rec_a")
    assert ts_current is not None
    assert ts_current["version"] == "job-1"


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
    row = state_service.get_row("rec_a")
    assert row is not None
    assert row.state.value == "released"
    # New ts row is current; the prior one is superseded.
    ts_current = repo_releases.current_release("ts", "rec_a")
    assert ts_current is not None
    assert ts_current["version"] == "job-new"
    ts_old = repo_releases.release_by_version("ts", "rec_a", "job-old")
    assert ts_old is not None
    assert ts_old["superseded_at"] is not None
    # HF membership stamped stale so the operator is driven to re-publish.
    hf_current = repo_releases.current_release("hf", "rec_a")
    assert hf_current is not None
    assert hf_current["stale_since"] is not None
    # Audit trail carries the distinct regen event.
    events = [
        r for r in repo_transitions.for_slug("rec_a") if r["event"] == "reciter.ts_regenerated"
    ]
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
    ts_current = repo_releases.current_release("ts", "rec_a")
    assert ts_current is not None
    assert ts_current["version"] == "job-old"


def test_complete_regen_stales_report_whose_content_changed(monkeypatch):
    """A regen on a released reciter flags an open report stale when the new
    shard changed its targeted content (here: a dropped tajweed rule)."""
    from services import db
    from services.db import repo_ts_reports
    from services.ts_reports import ts_target_snapshot

    _seed_released_with_ledger("rec_a", ts_version="job-old")
    monkeypatch.setattr(timestamps_jobs, "_has_any_shard", lambda slug: True)

    with db.transaction():
        row, _ = repo_ts_reports.create(
            slug="rec_a",
            verse_key="2:45",
            category="tajweed",
            subtype="wrong_rule",
            target={"kind": "cell", "word_index": 0, "cell_index": 0},
            snapshot={
                "chars": "ب",
                "role": "base",
                "status": "present",
                "tag": "qalqala_sughra",
                "secondary_tags": [],
                "phoneme_rule_tags": [],
            },
            comment=None,
            hf_user_id=None,
            anon_token="anon-1",
            login_at_time=None,
            role_at_time=None,
        )

    # The regenerated shard drops the qalqala rule on that cell.
    changed = {
        "_meta": {"schema_version": 9, "chapter": 2, "audio_category": "by_ayah_audio"},
        "segments": [
            {
                "ref": "2:45",
                "t": [0, 20],
                "words": [
                    [
                        1,
                        0,
                        20,
                        [["ب", 0, 10]],
                        [["b", 0, 10]],
                        [["ب", "base", "present", [0], 0, None, None]],
                    ]
                ],
            }
        ],
    }
    monkeypatch.setattr(ts_target_snapshot, "_load_shard", lambda slug, ch: changed)

    timestamps_jobs.complete_timestamps_job("rec_a", "job-new")

    got = repo_ts_reports.get(row["id"])
    assert got is not None and got["stale"] is True


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
    row = state_service.get_row("rec_a")
    assert row is not None
    assert row.state.value == "under_review"


def test_complete_refuses_when_no_shards(monkeypatch):
    from services.state import state as state_service

    _seed_marked_ready("rec_a")
    monkeypatch.setattr(timestamps_jobs, "_has_any_shard", lambda slug: False)

    out = timestamps_jobs.complete_timestamps_job("rec_a", "job-1")

    assert out["released"] is False
    assert out["reason"] == "no shards"
    row = state_service.get_row("rec_a")
    assert row is not None
    assert row.state.value == "under_review"


def test_complete_is_idempotent_on_double_call(monkeypatch):
    from services.state import state as state_service

    _seed_marked_ready("rec_a")
    monkeypatch.setattr(timestamps_jobs, "_has_any_shard", lambda slug: True)

    first = timestamps_jobs.complete_timestamps_job("rec_a", "job-1")
    second = timestamps_jobs.complete_timestamps_job("rec_a", "job-1")

    assert first["released"] is True
    assert second["released"] is False  # already released → no-op
    row = state_service.get_row("rec_a")
    assert row is not None
    assert row.state.value == "released"


def test_complete_unknown_slug_is_noop():
    out = timestamps_jobs.complete_timestamps_job("nope", "job-1")
    assert out["released"] is False
    assert out["reason"] == "unknown slug"
    # state must be None for unknown slugs — pin so a regression that
    # synthesizes a phantom state can't slip through.
    assert out["state"] is None


# ---------------------------------------------------------------------------
# Job completion → publish / state
# ---------------------------------------------------------------------------


def test_complete_publishes_marked_ready_reciter(monkeypatch):
    """A successful job on a marked-ready reciter auto-releases it (the
    Ready-to-generate → Publish-to-HF transition)."""
    _seed_marked_ready("rec_a")
    monkeypatch.setattr(timestamps_jobs, "_has_any_shard", lambda slug: True)

    out = timestamps_jobs.complete_timestamps_job("rec_a", "job-1")
    assert out["released"] is True


def test_failure_leaves_reciter_under_review():
    from services.state import state as state_service

    _seed_marked_ready("rec_a")
    timestamps_jobs.note_timestamps_job_failed("rec_a")
    row = state_service.get_row("rec_a")
    assert row is not None
    assert row.state.value == "under_review"  # no publish
