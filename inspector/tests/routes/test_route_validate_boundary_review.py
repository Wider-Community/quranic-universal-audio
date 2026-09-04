"""``GET /api/seg/validate`` — boundary-review categories are gated on
``segments.view_boundary_review`` per viewer, while the cached payload stays
complete."""

from __future__ import annotations

import json

import pytest

from services.storage.data_loader import load_detailed
from tests.classifier.test_boundary_review import FALSE_ENTRY, HIDDEN_ENTRY

RECITER = "fixture_reciter"


@pytest.fixture
def with_sidecars(tmp_path, tmp_reciter_dir):
    tmp_reciter_dir.install(RECITER, "112-ikhlas")
    d = tmp_path / "reciters" / RECITER
    uid = load_detailed(RECITER)[0]["segments"][0]["segment_uid"]
    (d / "hidden_pause_v1.json").write_text(
        json.dumps({"_meta": {"kind": "hidden_pause"}, "by_uid": {uid: HIDDEN_ENTRY}}), "utf-8"
    )
    (d / "false_split_v1.json").write_text(
        json.dumps({"_meta": {"kind": "false_split"}, "by_uid": {uid: FALSE_ENTRY}}), "utf-8"
    )
    return uid


def _get(client):
    res = client.get(f"/api/seg/validate/{RECITER}")
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_json()


def test_anonymous_viewer_gets_no_boundary_review(flask_client, with_sidecars):
    body = _get(flask_client)
    assert "hidden_pause" not in body
    assert "false_split" not in body
    assert "hidden_pause_meta" not in body
    assert body["category_counts"]["hidden_pause"] == 0
    assert body["category_counts"]["false_split"] == 0


def test_contributor_gets_no_boundary_review(signed_in_client, with_sidecars):
    client, _ = signed_in_client(role="contributor")
    body = _get(client)
    assert "hidden_pause" not in body
    assert body["category_counts"]["false_split"] == 0


@pytest.mark.parametrize("role", ["maintainer", "owner"])
def test_maintainer_and_owner_see_boundary_review(signed_in_client, with_sidecars, role):
    client, _ = signed_in_client(role=role)
    body = _get(client)
    assert body["category_counts"]["hidden_pause"] == 1
    assert body["category_counts"]["false_split"] == 1
    assert body["hidden_pause"][0]["segment_uid"] == with_sidecars
    assert body["hidden_pause"][0]["boundary"]["refs"] == HIDDEN_ENTRY["refs"]
    assert body["false_split"][0]["boundary"]["next_uid"] == "u2"
    assert body["hidden_pause_meta"] == {"kind": "hidden_pause"}


def test_gate_is_per_viewer_across_the_shared_cache(flask_client, signed_in_client, with_sidecars):
    assert "hidden_pause" not in _get(flask_client)
    client, _ = signed_in_client(role="maintainer")
    assert _get(client)["category_counts"]["hidden_pause"] == 1
    assert "hidden_pause" not in _get(flask_client)


def test_auto_split_map_merges_hidden_pause_refs(signed_in_client, with_sidecars):
    client, _ = signed_in_client(role="maintainer")
    res = client.get(f"/api/seg/auto-split/{RECITER}")
    assert res.status_code == 200
    entry = res.get_json()["by_uid"][with_sidecars]
    assert entry == {"cursors": [1500], "refs": HIDDEN_ENTRY["refs"], "kind": "hidden_pause"}
