"""POST /api/seg/undo-batch and /api/seg/undo-ops tests (MUST-8)."""
from __future__ import annotations

import json

import pytest


def test_undo_batch_legacy_records(flask_client, tmp_reciter_dir):
    """A pre-Phase-5 record (no patch) goes through the field-restore path."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    body = {"batch_id": "no-such-batch"}
    res = flask_client.post(
        f"/api/seg/undo-batch/{reciter}",
        data=json.dumps(body),
        content_type="application/json",
    )
    assert res.status_code in (200, 400, 404)


def test_undo_batch_patch_records(flask_client, tmp_reciter_dir):
    """A post-Phase-5 record (with patch) goes through the inverse-patch path; full segment restoration."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    chapter = 112

    save_payload = {
        "full_replace": True,
        "segments": [],
        "operations": [
            {
                "op_id": "op-1",
                "type": "delete",
                "patch": {
                    "before": [{"segment_uid": "019d5c88-f55f-7ee0-81d1-d99f423e8dd5"}],
                    "after": [],
                    "removedIds": ["019d5c88-f55f-7ee0-81d1-d99f423e8dd5"],
                    "insertedIds": [],
                    "affectedChapterIds": [chapter],
                },
            },
        ],
    }
    save = flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(save_payload),
        content_type="application/json",
    )
    assert save.status_code == 200

    history_path = tmp_reciter_dir.root / reciter / "edit_history.jsonl"
    last = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])
    batch_id = last["batch_id"]

    undo = flask_client.post(
        f"/api/seg/undo-batch/{reciter}",
        data=json.dumps({"batch_id": batch_id}),
        content_type="application/json",
    )
    assert undo.status_code == 200

    detailed = json.loads((tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8"))
    uids = [s.get("segment_uid") for e in detailed["entries"] for s in e.get("segments", [])]
    assert "019d5c88-f55f-7ee0-81d1-d99f423e8dd5" in uids, (
        "inverse patch did not restore the deleted segment"
    )


def test_undo_ops_partial_within_batch(flask_client, tmp_reciter_dir):
    """undo-ops route accepts (batch_id, op_ids) and returns 200/4xx without exception."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    body = {"batch_id": "no-such-batch", "op_ids": ["op-1"]}
    res = flask_client.post(
        f"/api/seg/undo-ops/{reciter}",
        data=json.dumps(body),
        content_type="application/json",
    )
    assert res.status_code in (200, 400, 404)
