"""GET /api/seg/edit-history/<reciter> tests (MUST-1)."""
from __future__ import annotations

import json

import pytest


def test_history_response_shape(flask_client, tmp_reciter_dir, load_expected):
    """edit-history route returns at least the frozen MUST-1 baseline field set."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    baseline = load_expected("112-ikhlas", "routes")
    expected_keys = baseline["edit_history"]["field_keys_top_level"]

    res = flask_client.get(f"/api/seg/edit-history/{reciter}")
    assert res.status_code in (200, 404)
    if res.status_code == 200:
        body = res.get_json()
        assert isinstance(body, (dict, list))
        if isinstance(body, dict) and expected_keys:
            from tests.conftest import assert_keys_superset
            assert_keys_superset(expected_keys, list(body.keys()), "GET /api/seg/edit-history")


@pytest.mark.xfail(reason="phase-2", strict=False)
def test_history_record_includes_classified_issues_on_snapshots(flask_client, tmp_reciter_dir):
    """Phase 2: history record snapshots persist classified_issues."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    save = flask_client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps({"full_replace": True, "segments": [], "operations": [{"op_id": "op-1", "type": "edit_reference", "snapshots": {"before": {}, "after": {}}}]}),
        content_type="application/json",
    )
    assert save.status_code == 200

    history_path = tmp_reciter_dir.root / reciter / "edit_history.jsonl"
    last_line = history_path.read_text(encoding="utf-8").splitlines()[-1]
    record = json.loads(last_line)
    op = record["operations"][0]
    snaps = op.get("snapshots") or {}
    for which in ("before", "after"):
        snap = snaps.get(which) or {}
        assert "classified_issues" in snap, (
            f"snapshot {which} missing classified_issues field (Phase 2 IS-4)"
        )


@pytest.mark.xfail(reason="phase-5", strict=False)
def test_history_record_includes_patch_when_present(flask_client, tmp_reciter_dir):
    """Phase 5: GET /edit-history endpoint surfaces the persisted patch in its response.

    Pre-Phase-5 the route serializes whatever's in the JSONL log; Phase 5
    introduces an explicit `patch` field on every returned op, even legacy
    records (synthesized from the saved snapshot). Test verifies the
    response shape post-Phase-5.
    """
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    res = flask_client.get(f"/api/seg/edit-history/{reciter}")
    assert res.status_code == 200
    body = res.get_json()
    batches = body.get("batches") if isinstance(body, dict) else None
    if not batches:
        # No history yet — Phase 5 must still surface the field shape on
        # later batches; absence of batches keeps the test in xfail.
        raise AssertionError("phase-5: no batches yet to inspect for patch field")
    for batch in batches:
        for op in batch.get("operations") or []:
            assert "patch" in op, (
                "Phase 5: edit-history must include patch on every op"
            )
