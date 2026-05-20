"""/healthz surfaces the SQLite-substrate status only when the flag is on,
and is unchanged (no `db` key) when off — the default during transition."""

from __future__ import annotations

import pytest

from services import db


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


def test_healthz_has_no_db_section_when_flag_off(client, monkeypatch):
    monkeypatch.delenv("INSPECTOR_STORE_BACKEND", raising=False)
    body = client.get("/healthz").get_json()
    assert "db" not in body
    assert body["status"] in ("ok", "degraded")


def test_healthz_reports_db_when_flag_on(client, monkeypatch, tmp_path):
    monkeypatch.setenv("INSPECTOR_STORE_BACKEND", "sqlite")
    db.set_db_path_for_test(tmp_path / "health.db")
    db.init_db()
    try:
        body = client.get("/healthz").get_json()
        assert "db" in body
        assert body["db"]["open"] is True
        assert body["db"]["schema_version"] == 1
        # no upload yet → lag is None, no error
        assert body["db"]["bucket_lag_seconds"] is None
        assert body["db"]["last_error"] is None
    finally:
        db.reset()


def test_substrate_enabled_flag(monkeypatch):
    monkeypatch.delenv("INSPECTOR_STORE_BACKEND", raising=False)
    assert db.substrate_enabled() is False
    monkeypatch.setenv("INSPECTOR_STORE_BACKEND", "sqlite")
    assert db.substrate_enabled() is True
    monkeypatch.setenv("INSPECTOR_STORE_BACKEND", "json")
    assert db.substrate_enabled() is False
