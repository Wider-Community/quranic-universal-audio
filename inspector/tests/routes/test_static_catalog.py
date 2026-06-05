"""Static-data route: GET /api/static/catalog.json (D20 Track B)."""

from __future__ import annotations

from qua_shared.schemas import ReciterCatalog


def test_catalog_route_serves_valid_catalog_json(flask_client, tmp_reciter_dir):
    """Route returns the in-memory catalog as JSON parseable by ``ReciterCatalog``."""
    res = flask_client.get("/api/static/catalog.json")

    assert res.status_code == 200
    assert res.mimetype == "application/json"

    body = res.get_json()
    assert isinstance(body, dict)
    # Pydantic must round-trip — guarantees the JSON shape matches the schema.
    parsed = ReciterCatalog.model_validate(body)
    assert parsed.schema_version >= 1
    # Empty catalog is valid (tmp_reciter_dir hydrates a fresh empty store).
    assert isinstance(parsed.reciters, list)
    assert isinstance(parsed.deliveries, list)


def test_catalog_route_sets_cache_control(flask_client, tmp_reciter_dir):
    """Route sets a short Cache-Control so catalog edits propagate quickly."""
    res = flask_client.get("/api/static/catalog.json")

    assert res.status_code == 200
    cache_control = res.headers.get("Cache-Control", "")
    assert "max-age=300" in cache_control
    assert "public" in cache_control


def test_ts_config_advertises_catalog_url(flask_client):
    """``/api/ts/config`` carries ``catalog_url`` so the frontend can find the catalog route."""
    res = flask_client.get("/api/ts/config")

    assert res.status_code == 200
    body = res.get_json()
    assert body.get("catalog_url") == "/api/static/catalog.json"
    # Legacy manifest_url stays as fallback.
    assert "manifest_url" in body
    assert "shard_url_template" in body
