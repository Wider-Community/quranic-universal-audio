"""HTTP boundary tests for the internal admin endpoints.

``POST /api/admin/internal/ts-refreshed`` — secret-gated (``X-Inspector-Job-Secret``
vs ``INSPECTOR_WEBHOOK_SECRET``), no OAuth/CSRF. Verifies the disabled (no
secret) / unauthorized / success paths, that a success advances the current ts
release ``produced_at`` and emits ``reciter.ts_refreshed``, and the
no-current-ts-row ack.
"""

from __future__ import annotations

from datetime import UTC, datetime

_URL = "/api/admin/internal/ts-refreshed"
_SECRET = "test-internal-secret"


def _seed_ts_release(slug: str, *, produced_at: datetime) -> None:
    """Insert a current ts release row for ``slug`` (+ its FK delivery chain)."""
    from services import db
    from services.db import repo_releases
    from tests.conftest import _seed_delivery_chain

    with db.transaction() as conn:
        _seed_delivery_chain(conn, slug)
        repo_releases.insert_per_recitation_release(
            track="ts", slug=slug, version="job-1", produced_at=produced_at, produced_by="a"
        )


def test_disabled_when_secret_unset(flask_client, monkeypatch):
    monkeypatch.delenv("INSPECTOR_WEBHOOK_SECRET", raising=False)
    resp = flask_client.post(_URL, json={"slug": "rec_a"})
    assert resp.status_code == 503


def test_rejects_bad_secret(flask_client, monkeypatch):
    monkeypatch.setenv("INSPECTOR_WEBHOOK_SECRET", _SECRET)
    resp = flask_client.post(
        _URL, json={"slug": "rec_a"}, headers={"X-Inspector-Job-Secret": "wrong"}
    )
    assert resp.status_code == 401


def test_rejects_missing_secret_header(flask_client, monkeypatch):
    monkeypatch.setenv("INSPECTOR_WEBHOOK_SECRET", _SECRET)
    resp = flask_client.post(_URL, json={"slug": "rec_a"})
    assert resp.status_code == 401


def test_rejects_missing_slug(flask_client, monkeypatch):
    monkeypatch.setenv("INSPECTOR_WEBHOOK_SECRET", _SECRET)
    resp = flask_client.post(_URL, json={}, headers={"X-Inspector-Job-Secret": _SECRET})
    assert resp.status_code == 400


def test_refresh_advances_produced_at_and_emits_event(flask_client, monkeypatch):
    monkeypatch.setenv("INSPECTOR_WEBHOOK_SECRET", _SECRET)
    slug = "rec_refresh"
    _seed_ts_release(slug, produced_at=datetime(2020, 1, 1, tzinfo=UTC))

    resp = flask_client.post(
        _URL,
        json={"slug": slug, "chapters": [2, 5], "reason": "backfill_cells"},
        headers={"X-Inspector-Job-Secret": _SECRET},
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True and body["refreshed"] is True

    from services.db import repo_releases, repo_transitions

    ts_row = repo_releases.current_release("ts", slug)
    assert ts_row is not None
    # produced_at advanced past the seeded 2020 watermark (no override → server now()).
    assert ts_row["produced_at"] > "2020-01-01"
    events = [t for t in repo_transitions.for_slug(slug) if t["event"] == "reciter.ts_refreshed"]
    assert len(events) == 1
    assert events[0]["payload"]["chapters"] == [2, 5]
    assert events[0]["payload"]["reason"] == "backfill_cells"


def test_refresh_with_produced_at_override(flask_client, monkeypatch):
    monkeypatch.setenv("INSPECTOR_WEBHOOK_SECRET", _SECRET)
    slug = "rec_override"
    _seed_ts_release(slug, produced_at=datetime(2020, 1, 1, tzinfo=UTC))

    resp = flask_client.post(
        _URL,
        json={"slug": slug, "produced_at": "2026-03-15T00:00:00Z"},
        headers={"X-Inspector-Job-Secret": _SECRET},
    )

    assert resp.status_code == 200
    from services.db import repo_releases

    ts_row = repo_releases.current_release("ts", slug)
    assert ts_row is not None
    assert ts_row["produced_at"].startswith("2026-03-15")


def test_refresh_unknown_reciter_acks_not_refreshed(flask_client, monkeypatch):
    monkeypatch.setenv("INSPECTOR_WEBHOOK_SECRET", _SECRET)
    resp = flask_client.post(
        _URL,
        json={"slug": "never_generated"},
        headers={"X-Inspector-Job-Secret": _SECRET},
    )
    assert resp.status_code == 200
    assert resp.get_json()["refreshed"] is False
