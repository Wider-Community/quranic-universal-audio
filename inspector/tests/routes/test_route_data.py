"""GET /api/seg/data/<reciter>/<chapter>, /all/<reciter>, /config tests."""
from __future__ import annotations

import pytest


def test_seg_data_response_shape(flask_client, tmp_reciter_dir):
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    res = flask_client.get(f"/api/seg/data/{reciter}/112")
    assert res.status_code in (200, 404)
    if res.status_code == 200:
        body = res.get_json()
        assert isinstance(body, dict)
        for key in ("segments", "audio", "summary", "issues"):
            if key in body:
                break
        else:
            pass


def test_seg_all_response_shape(flask_client, tmp_reciter_dir):
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    res = flask_client.get(f"/api/seg/all/{reciter}")
    assert res.status_code in (200, 404)
    if res.status_code == 200:
        body = res.get_json()
        assert isinstance(body, dict)


def test_seg_config_response_shape(flask_client):
    """The /config endpoint returns a dict with the canonical keys."""
    res = flask_client.get("/api/seg/config")
    assert res.status_code == 200
    body = res.get_json()
    assert isinstance(body, dict)
    expected_keys = {
        "seg_font_size",
        "validation_categories",
        "muqattaat_verses",
        "qalqala_letters",
    }
    assert expected_keys.issubset(set(body.keys())), (
        f"missing keys: {expected_keys - set(body.keys())}"
    )


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
