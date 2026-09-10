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
    # Test fixture does not set INSPECTOR_BUCKET_MOUNT, so bucket_ok is False
    # and the route deterministically reports the degraded branch. Pin it.
    assert body["status"] == "degraded"


def test_default_healthz_omits_sample_validation(client):
    # The deep probe is opt-in: without ?deep=1 the route must never walk the
    # bucket, so the field is absent on the default path.
    body = client.get("/healthz").get_json()
    assert "sample_validation" not in body


def test_deep_healthz_adds_sample_validation_block(client, state_persistence):
    # state_persistence installs a FilesystemBackend singleton, so the deep
    # probe stays offline. No reciters under reciters/ → empty sample, and the
    # autouse DB has a clean (reciter-less) catalog → catalog_ok True.
    body = client.get("/healthz?deep=1").get_json()

    sv = body["sample_validation"]
    assert sv["catalog_ok"] is True
    assert sv["sampled"] == []
    assert sv["n_reciters"] == 0
    assert sv["ok"] is True
    assert sv["errors"] == []


def test_healthz_reports_the_optional_edition_package(client):
    from services.reference import editions

    block = client.get("/healthz").get_json()["editions"]
    assert block["available"] is editions.available()
    assert block["riwayat"] == editions.all_riwayat()
    # A clean catalog has no deliveries at all, so nothing is unservable and the
    # field is omitted whether or not the package is installed.
    assert "unservable_riwayat" not in block


def test_healthz_degrades_when_a_non_hafs_delivery_cannot_be_served(client, monkeypatch):
    from routes.auth import health

    from services.reference import editions

    monkeypatch.setattr(editions, "available", lambda: False)
    monkeypatch.setattr(editions, "all_riwayat", list)
    monkeypatch.setattr(
        "services.db.repo_catalog.deliveries_per_riwayah",
        lambda: {"hafs_an_asim": 37, "warsh_an_nafi": 1},
    )
    block, healthy = health._editions_health()
    assert healthy is False
    assert block["unservable_riwayat"] == ["warsh_an_nafi"]


def test_healthz_stays_healthy_on_a_hafs_only_catalog_without_the_package(monkeypatch):
    from routes.auth import health

    from services.reference import editions

    monkeypatch.setattr(editions, "available", lambda: False)
    monkeypatch.setattr(editions, "all_riwayat", list)
    monkeypatch.setattr(
        "services.db.repo_catalog.deliveries_per_riwayah", lambda: {"hafs_an_asim": 37}
    )
    block, healthy = health._editions_health()
    assert healthy is True
    assert "unservable_riwayat" not in block
