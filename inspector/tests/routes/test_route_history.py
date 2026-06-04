"""GET /api/seg/edit-history/<reciter> tests (MUST-1)."""

from __future__ import annotations

import json

import pytest

_SAVE_HEADERS = {"Content-Type": "application/json", "Origin": "http://localhost"}


def test_history_response_shape(flask_client, tmp_reciter_dir, load_expected):
    """edit-history route returns at least the frozen MUST-1 baseline field set."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    baseline = load_expected("112-ikhlas", "routes")
    expected_keys = baseline["edit_history"]["field_keys_top_level"]

    res = flask_client.get(f"/api/seg/edit-history/{reciter}")
    assert res.status_code == 200, res.get_data(as_text=True)
    body = res.get_json()
    assert isinstance(body, (dict, list))
    if isinstance(body, dict) and expected_keys:
        from tests.conftest import assert_keys_superset

        assert_keys_superset(expected_keys, list(body.keys()), "GET /api/seg/edit-history")


def test_history_record_includes_classified_issues_on_snapshots(
    signed_in_client,
    tmp_reciter_dir,
):
    """History record snapshots persist classified_issues."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")

    save = client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps(
            {
                "full_replace": True,
                "segments": [],
                "operations": [
                    {
                        "op_id": "op-1",
                        "type": "edit_reference",
                        "command": {"type": "edit_reference", "segmentUid": "x"},
                        "snapshots": {"before": {}, "after": {}},
                    }
                ],
            }
        ),
        headers=_SAVE_HEADERS,
    )
    assert save.status_code == 200

    history_path = tmp_reciter_dir.root / reciter / "edit_history.jsonl"
    last_line = history_path.read_text(encoding="utf-8").splitlines()[-1]
    record = json.loads(last_line)
    op = record["operations"][0]
    snaps = op.get("snapshots") or {}
    for which in ("before", "after"):
        snap = snaps.get(which) or {}
        assert "classified_issues" in snap, f"snapshot {which} missing classified_issues field"


def test_history_record_includes_patch_when_present(flask_client, tmp_reciter_dir):
    """GET /edit-history surfaces an explicit ``patch`` field on every op.

    Synthesized from the saved snapshot for records that don't carry one.
    Skip when the fixture has no batches (the patch invariant only applies
    to records that exist).
    """
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    res = flask_client.get(f"/api/seg/edit-history/{reciter}")
    assert res.status_code == 200
    body = res.get_json()
    batches = body.get("batches") if isinstance(body, dict) else None
    if not batches:
        pytest.skip("no batches in fixture to inspect for patch field")
    for batch in batches:
        for op in batch.get("operations") or []:
            assert "patch" in op, "edit-history must include patch on every op"
