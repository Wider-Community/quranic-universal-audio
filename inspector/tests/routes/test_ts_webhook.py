"""HTTP boundary tests for the timestamps-job completion webhook.

``POST /api/webhooks/ts-job-complete`` — secret-gated, no OAuth/CSRF. Verifies
the disabled (no secret) / unauthorized / success paths and that a non-success
status is acked without publishing.
"""

from __future__ import annotations

_URL = "/api/webhooks/ts-job-complete"
_SECRET = "test-webhook-secret"


def _spy_complete(monkeypatch):
    """Replace the orchestrator with a spy that records its calls."""
    from services.admin import timestamps_jobs

    calls: list[tuple[str, str]] = []

    def _fake(slug, job_id):
        calls.append((slug, job_id))
        return {"slug": slug, "state": "released", "released": True}

    monkeypatch.setattr(timestamps_jobs, "complete_timestamps_job", _fake)
    return calls


def test_webhook_disabled_when_secret_unset(flask_client, monkeypatch):
    monkeypatch.delenv("INSPECTOR_WEBHOOK_SECRET", raising=False)
    calls = _spy_complete(monkeypatch)

    resp = flask_client.post(_URL, json={"slug": "r", "job_id": "j", "status": "succeeded"})

    assert resp.status_code == 503
    assert calls == []


def test_webhook_rejects_bad_secret(flask_client, monkeypatch):
    monkeypatch.setenv("INSPECTOR_WEBHOOK_SECRET", _SECRET)
    calls = _spy_complete(monkeypatch)

    resp = flask_client.post(
        _URL,
        json={"slug": "r", "job_id": "j", "status": "succeeded"},
        headers={"X-Inspector-Job-Secret": "wrong"},
    )

    assert resp.status_code == 401
    assert calls == []


def test_webhook_rejects_missing_secret_header(flask_client, monkeypatch):
    monkeypatch.setenv("INSPECTOR_WEBHOOK_SECRET", _SECRET)
    calls = _spy_complete(monkeypatch)

    resp = flask_client.post(_URL, json={"slug": "r", "job_id": "j", "status": "succeeded"})

    assert resp.status_code == 401
    assert calls == []


def test_webhook_publishes_on_success(flask_client, monkeypatch):
    monkeypatch.setenv("INSPECTOR_WEBHOOK_SECRET", _SECRET)
    calls = _spy_complete(monkeypatch)

    resp = flask_client.post(
        _URL,
        json={"slug": "rec_a", "job_id": "job-1", "status": "succeeded"},
        headers={"X-Inspector-Job-Secret": _SECRET},
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True and body["released"] is True
    assert calls == [("rec_a", "job-1")]


def test_webhook_notifies_on_failure_without_publishing(flask_client, monkeypatch):
    from services.admin import timestamps_jobs

    monkeypatch.setenv("INSPECTOR_WEBHOOK_SECRET", _SECRET)
    published = _spy_complete(monkeypatch)
    noted: list[str] = []
    monkeypatch.setattr(
        timestamps_jobs,
        "note_timestamps_job_failed",
        lambda slug: (noted.append(slug), {"slug": slug, "noted": True})[1],
    )

    resp = flask_client.post(
        _URL,
        json={"slug": "rec_a", "job_id": "job-1", "status": "failed"},
        headers={"X-Inspector-Job-Secret": _SECRET},
    )

    assert resp.status_code == 200
    assert published == []  # a failed job is never published
    assert noted == ["rec_a"]  # but it lights the Marked-ready dot


def test_webhook_requires_slug_and_job_id(flask_client, monkeypatch):
    monkeypatch.setenv("INSPECTOR_WEBHOOK_SECRET", _SECRET)
    _spy_complete(monkeypatch)

    resp = flask_client.post(
        _URL,
        json={"status": "succeeded"},
        headers={"X-Inspector-Job-Secret": _SECRET},
    )

    assert resp.status_code == 400
