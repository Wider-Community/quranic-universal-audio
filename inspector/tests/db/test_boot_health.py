"""/healthz surfaces the SQLite-substrate status unconditionally post-cutover
(the DB is the source of truth — there is no JSON fallback flag)."""

from __future__ import annotations

import pytest

from services import db


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


def test_healthz_reports_db_section(client):
    # The autouse _substrate_db fixture has opened + migrated a DB.
    body = client.get("/healthz").get_json()
    assert "db" in body
    assert body["db"]["open"] is True
    assert body["db"]["schema_version"] == 1
    # no upload yet → lag is None, no error
    assert body["db"]["bucket_lag_seconds"] is None
    assert body["db"]["last_error"] is None
    assert body["status"] in ("ok", "degraded")


def test_healthz_db_open_reflects_healthcheck(client):
    assert db.healthcheck()["open"] is True
    body = client.get("/healthz").get_json()
    assert body["db"]["open"] is True
