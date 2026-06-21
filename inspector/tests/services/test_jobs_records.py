"""Tests for the unified job-record store + aggregator.

Pins the single-store contract the admin Jobs tab depends on:
  - ``record_launch`` → ``record_terminal`` merges (launch fields survive).
  - ``read`` injects ``kind`` so legacy TS records (``type='ts'``, no ``kind``)
    parse uniformly + status normalizes to running/succeeded/failed.
  - ``list_all`` enumerates BOTH path namespaces (global + per-slug).
  - ``registry.list_all_jobs`` dedups live-over-record by job_id + sorts desc;
    ``job_detail`` surfaces batch/cut members.

All bucket + HF I/O is faked with an in-memory store so the tests are hermetic.
"""

from __future__ import annotations

import json

import pytest

from services.admin.jobs import base, records, registry


class _FakeBackend:
    def __init__(self, store: dict[str, bytes]):
        self.store = store

    def list_dir(self, path: str) -> list[str]:
        prefix = path.rstrip("/") + "/"
        out = []
        for p in self.store:
            if p.startswith(prefix):
                rest = p[len(prefix) :]
                if "/" not in rest:
                    out.append(rest)
        return out


@pytest.fixture
def store(monkeypatch):
    """In-memory record store wired into ``base``'s read/write/list + url + cache."""
    data: dict[str, bytes] = {}

    def _write(kind, slug, job_id, payload):
        data[base.job_record_path(kind, slug, job_id)] = payload

    def _read(kind, slug, job_id):
        return data.get(base.job_record_path(kind, slug, job_id))

    monkeypatch.setattr(base, "write_record_bytes", _write)
    monkeypatch.setattr(base, "read_record_bytes", _read)
    monkeypatch.setattr(base, "get_backend", lambda: _FakeBackend(data))
    monkeypatch.setattr(base, "hf_job_url", lambda job_id: None)
    from services.storage import cache as _cache

    _cache.invalidate_all_jobs_cache()
    return data


def test_launch_then_terminal_merges(store):
    records.record_launch("hf_publish", "reciter_x", "jid1", url="u://job", launched_by="me")
    rec = records.read("hf_publish", "reciter_x", "jid1")
    assert rec is not None
    assert rec.status == "running"
    assert rec.url == "u://job"
    assert rec.started_at is not None
    assert rec.ended_at is None

    records.record_terminal(
        "hf_publish", "reciter_x", "jid1", status="succeeded", version="v1", external_uri="e://ds"
    )
    rec2 = records.read("hf_publish", "reciter_x", "jid1")
    assert rec2.status == "succeeded"
    assert rec2.version == "v1"
    assert rec2.external_uri == "e://ds"
    # Launch fields survive the merge.
    assert rec2.url == "u://job"
    assert rec2.launched_by == "me"
    assert rec2.started_at == rec.started_at
    assert rec2.ended_at is not None


def test_terminal_without_prior_launch_writes_fresh(store):
    records.record_terminal("refresh_catalog", None, "jidR", status="failed", error="boom")
    rec = records.read("refresh_catalog", None, "jidR")
    assert rec is not None
    assert rec.kind == "refresh_catalog"
    assert rec.status == "failed"
    assert rec.error == "boom"


def test_read_injects_kind_and_normalizes_legacy_ts(store):
    # A legacy TS record: type='ts', no 'kind', raw HF status.
    path = base.job_record_path("timestamps", "reciter_x", "jidTS")
    store[path] = json.dumps(
        {"job_id": "jidTS", "slug": "reciter_x", "type": "ts", "status": "timed-out"}
    ).encode()
    rec = records.read("timestamps", "reciter_x", "jidTS")
    assert rec.kind == "timestamps"
    assert rec.status == "failed"  # timed-out → failed


def test_list_all_enumerates_global_and_per_slug(store, monkeypatch):
    records.record_terminal(
        "cut_release", None, "jidCut", status="succeeded", version="v0.1.0", members=[{"slug": "a"}]
    )
    records.record_launch("timestamps", "reciter_x", "jidTS", url="u")

    class _Row:
        slug = "reciter_x"

    from services.state import state as _state_mod

    monkeypatch.setattr(_state_mod, "all_rows", lambda: [_Row()])
    all_recs = records.list_all()
    ids = {r.job_id for r in all_recs}
    assert ids == {"jidCut", "jidTS"}


def test_registry_dedups_live_over_record_and_sorts_desc(store, monkeypatch):
    records.record_terminal("cut_release", None, "old", status="succeeded")
    records.record_launch("hf_publish", "reciter_x", "live1", url="u")

    class _Row:
        slug = "reciter_x"

    from services.state import state as _state_mod

    monkeypatch.setattr(_state_mod, "all_rows", lambda: [_Row()])
    # ``live1`` is reported running by HF; ``new2`` is brand-new (no record yet).
    monkeypatch.setattr(
        base,
        "list_in_flight_jobs",
        lambda kinds: [
            {
                "kind": "hf_publish",
                "slug": "reciter_x",
                "job_id": "live1",
                "started_at": "2026-06-09T10:00:00Z",
                "url": "u",
            },
            {
                "kind": "cut_release",
                "slug": None,
                "job_id": "new2",
                "started_at": "2026-06-09T12:00:00Z",
                "url": "u2",
            },
        ],
    )
    jobs = registry.list_all_jobs()
    by_id = {j.job_id: j for j in jobs}
    # No duplicate of live1 (record + live merged into one).
    assert sum(1 for j in jobs if j.job_id == "live1") == 1
    assert by_id["live1"].status == "running"  # flipped to running by the live merge
    assert "new2" in by_id  # live-only job surfaced
    # Newest started_at first.
    starts = [j.started_at or "" for j in jobs]
    assert starts == sorted(starts, reverse=True)


def test_job_detail_surfaces_batch_members(store):
    records.record_terminal(
        "hf_publish_batch",
        None,
        "jidBatch",
        status="succeeded",
        members=[
            {"slug": "a", "status": "succeeded", "version": "rev1"},
            {"slug": "b", "status": "failed", "error": "oom"},
        ],
    )
    rec = registry.job_detail("hf_publish_batch", "jidBatch", None)
    assert rec is not None
    assert rec.member_count == 2
    slugs = {m.slug for m in rec.members}
    assert slugs == {"a", "b"}
    assert rec.kind == "hf_publish_batch"


def test_statusless_completed_record_reads_succeeded(store):
    # The batch HF Job self-writes {job_id, completed_at, members} with NO
    # top-level status — must read as succeeded, NOT default to running.
    path = base.job_record_path("hf_publish_batch", None, "jidNoStatus")
    store[path] = json.dumps(
        {
            "job_id": "jidNoStatus",
            "completed_at": "2026-06-09T05:00:00Z",
            "members": [{"slug": "a", "status": "succeeded"}],
        }
    ).encode()
    rec = records.read("hf_publish_batch", None, "jidNoStatus")
    assert rec is not None
    assert rec.status == "succeeded"


def test_timestamps_kind_maps_to_ts_dir(store):
    # The unified store must read/write timestamps records under jobs/ts/ (where
    # the TS HF-Job + legacy writer put them), not jobs/timestamps/.
    assert base.kind_dir("timestamps") == "ts"
    assert base.job_record_path("timestamps", "reciter_x", "j").endswith(
        "reciters/reciter_x/jobs/ts/j.json"
    )
    assert base.job_record_path("timestamps", None, "j") == "jobs/_global/ts/j.json"
    assert base.job_record_path("hf_publish", "reciter_x", "j").endswith(
        "reciters/reciter_x/jobs/hf_publish/j.json"
    )
    # a legacy TS record stored under jobs/ts/ is found by read + list_for_slug
    store[base.job_record_path("timestamps", "reciter_x", "tsjob")] = json.dumps(
        {"job_id": "tsjob", "slug": "reciter_x", "type": "ts", "status": "succeeded"}
    ).encode()
    rec = records.read("timestamps", "reciter_x", "tsjob")
    assert rec is not None and rec.kind == "timestamps" and rec.status == "succeeded"
    assert any(r.job_id == "tsjob" for r in records.list_for_slug("reciter_x"))


def test_write_record_bytes_round_trips_through_real_backend(state_persistence):
    # The ``store`` fixture stubs write/read_record_bytes, so the real
    # ``get_backend().write_bytes_atomic`` call is never exercised there — which
    # is how a wrong backend method name silently no-op'd every job-record write
    # in prod. Drive the real path against a FilesystemBackend.
    payload = json.dumps({"job_id": "jidRT", "status": "succeeded"}).encode()
    base.write_record_bytes("hf_publish_batch", None, "jidRT", payload)
    assert base.read_record_bytes("hf_publish_batch", None, "jidRT") == payload
