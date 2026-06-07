"""Tests for the batch HF-publish kind (``services.admin.jobs.hf_publish_batch``).

Covers the completion fan-out: ``complete()`` calls the single-publish
``hf_publish.complete`` once per *succeeded* member and skips failed members,
returning a ``{published, failed}`` summary. The single-publish handler itself
is stubbed (its DB-insert behaviour is covered by the hf_publish tests) — here
we assert the batch handler routes members correctly.
"""

from __future__ import annotations

from services.admin.jobs import hf_publish, hf_publish_batch


def test_complete_inserts_succeeded_members_only(monkeypatch):
    """Succeeded members each call hf_publish.complete; failed members don't."""
    calls: list[tuple[str, str]] = []

    def fake_complete(slug, job_id, **kwargs):
        calls.append((slug, job_id))
        return {"ok": True}

    monkeypatch.setattr(hf_publish, "complete", fake_complete)

    members = [
        {"slug": "ar.ok1", "status": "succeeded", "version": "sha1", "external_uri": "u1"},
        {"slug": "ar.bad", "status": "failed", "error": "boundary validation failed"},
        {"slug": "ar.ok2", "status": "succeeded", "version": "sha2", "external_uri": "u2"},
    ]

    result = hf_publish_batch.complete("job_batch_1", members=members, launched_by="op")

    assert result == {"ok": True, "published": 2, "failed": 1}
    assert calls == [("ar.ok1", "job_batch_1"), ("ar.ok2", "job_batch_1")]


def test_complete_counts_member_insert_failure_as_failed(monkeypatch):
    """A member whose hf_publish.complete raises is counted as failed, not
    published — the batch never aborts on one bad member."""

    def fake_complete(slug, job_id, **kwargs):
        if slug == "ar.raises":
            raise RuntimeError("db blew up")
        return {"ok": True}

    monkeypatch.setattr(hf_publish, "complete", fake_complete)

    members = [
        {"slug": "ar.ok", "status": "succeeded", "version": "sha"},
        {"slug": "ar.raises", "status": "succeeded", "version": "sha"},
    ]

    result = hf_publish_batch.complete("job_batch_2", members=members)

    assert result == {"ok": True, "published": 1, "failed": 1}


def test_complete_poll_path_reads_members_from_record(monkeypatch):
    """When called with members=None (poll fallback) the handler reads the
    durable batch record the job wrote to the bucket."""
    import json

    calls: list[str] = []
    monkeypatch.setattr(
        hf_publish, "complete", lambda slug, job_id, **kw: calls.append(slug) or {"ok": True}
    )
    record = {
        "job_id": "job_batch_3",
        "members": [{"slug": "ar.fromrecord", "status": "succeeded", "version": "sha"}],
    }
    monkeypatch.setattr(
        hf_publish_batch.base,
        "read_record_bytes",
        lambda kind, slug, job_id: json.dumps(record).encode("utf-8"),
    )

    result = hf_publish_batch.complete("job_batch_3")

    assert result["published"] == 1
    assert calls == ["ar.fromrecord"]
