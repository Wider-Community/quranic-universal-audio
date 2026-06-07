"""Unit tests for the history tier generation timeline.

``generation_timeline`` turns the TS-generation rows into ascending boundaries
and marks each one ``published`` when an HF publish landed in its interval. The
repo reads are stubbed so the test exercises the interval/publish-marker logic
(the SQL itself is covered in ``tests/db/test_repo_releases.py``).
"""

from __future__ import annotations

from services.db import repo_releases
from services.segments import history_tiers


def _stub_releases(monkeypatch, *, ts, hf):
    def fake(track, _slug):
        return ts if track == "ts" else hf

    monkeypatch.setattr(repo_releases, "all_releases_for_track_slug", fake)


def test_timeline_marks_published_generation(monkeypatch):
    _stub_releases(
        monkeypatch,
        ts=[
            {"version": "g1", "produced_at": "2026-01-01T00:00:00Z"},
            {"version": "g2", "produced_at": "2026-03-01T00:00:00Z"},
        ],
        # publish landed after g1, before g2 → g1 published, g2 not.
        hf=[{"produced_at": "2026-02-01T00:00:00Z"}],
    )
    timeline = history_tiers.generation_timeline("slug")
    assert [g["version"] for g in timeline] == ["g1", "g2"]
    assert timeline[0]["published"] is True
    assert timeline[0]["published_at"] == "2026-02-01T00:00:00Z"
    assert timeline[1]["published"] is False
    assert timeline[1]["published_at"] is None


def test_timeline_empty_when_never_generated(monkeypatch):
    _stub_releases(monkeypatch, ts=[], hf=[])
    assert history_tiers.generation_timeline("slug") == []


def test_publish_after_latest_generation_marks_it(monkeypatch):
    _stub_releases(
        monkeypatch,
        ts=[{"version": "g1", "produced_at": "2026-01-01T00:00:00Z"}],
        hf=[{"produced_at": "2026-01-02T00:00:00Z"}],
    )
    timeline = history_tiers.generation_timeline("slug")
    assert timeline[0]["published"] is True
