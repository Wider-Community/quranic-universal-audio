"""/healthz surfaces the SQLite-substrate status; the DB is the source of
truth and there is no JSON fallback flag."""

from __future__ import annotations

import pytest


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
    # Latest migration on disk (derived so a new migration doesn't break this).
    from services.db import migrate as _migrate
    assert body["db"]["schema_version"] == max(n for n, _ in _migrate._discover())
    # no upload yet → lag is None, no error
    assert body["db"]["bucket_lag_seconds"] is None
    assert body["db"]["last_error"] is None
    assert body["status"] in ("ok", "degraded")
