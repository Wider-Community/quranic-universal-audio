"""GET /api/seg/data/<reciter>/<chapter>, /all/<reciter>, /config tests (MUST-1)."""
from __future__ import annotations

import pytest

from tests.conftest import assert_keys_superset


def test_seg_data_response_shape(flask_client, tmp_reciter_dir, load_expected):
    """The /data endpoint returns at least the frozen MUST-1 baseline field set."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    baseline = load_expected("112-ikhlas", "routes")
    expected_keys = baseline["data"]["field_keys_top_level"]

    res = flask_client.get(f"/api/seg/data/{reciter}/112")
    assert res.status_code in (200, 404)
    if res.status_code == 200:
        body = res.get_json()
        assert isinstance(body, dict)
        assert_keys_superset(expected_keys, list(body.keys()), "GET /api/seg/data")


def test_seg_all_response_shape(flask_client, tmp_reciter_dir, load_expected):
    """The /all endpoint returns at least the frozen MUST-1 baseline field set."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    baseline = load_expected("112-ikhlas", "routes")
    expected_keys = baseline["all"]["field_keys_top_level"]

    res = flask_client.get(f"/api/seg/all/{reciter}")
    assert res.status_code in (200, 404)
    if res.status_code == 200:
        body = res.get_json()
        assert isinstance(body, dict)
        assert_keys_superset(expected_keys, list(body.keys()), "GET /api/seg/all")


def test_seg_config_response_shape(flask_client, load_expected):
    """The /config endpoint returns at least the frozen MUST-1 baseline field set."""
    baseline = load_expected("112-ikhlas", "routes")
    expected_keys = baseline["config"]["field_keys_top_level"]

    res = flask_client.get("/api/seg/config")
    assert res.status_code == 200
    body = res.get_json()
    assert isinstance(body, dict)
    assert_keys_superset(expected_keys, list(body.keys()), "GET /api/seg/config")


@pytest.mark.xfail(reason="phase-1", strict=False)
def test_seg_config_validation_categories_match_registry(flask_client):
    """The /config response's validation_categories list is registry-derived."""
    pytest.importorskip(
        "services.validation.registry",
        reason="phase-1 — IssueRegistry module not yet introduced",
    )
    from services.validation.registry import IssueRegistry  # type: ignore

    res = flask_client.get("/api/seg/config")
    body = res.get_json()
    config_cats = set(body.get("validation_categories") or [])
    registry_cats = set(IssueRegistry.keys())
    assert config_cats == registry_cats, (
        f"/config validation_categories {config_cats} != registry keys {registry_cats}"
    )
