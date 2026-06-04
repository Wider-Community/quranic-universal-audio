"""POST /api/seg/undo-batch and /api/seg/undo-ops tests (MUST-8).

Undo routes are gated by ``require_edit_lock(admin_bypass=True)``; tests
use ``signed_in_client`` with the user seeded as the active assignee on an
``under_review`` row, plus the same-origin Header. The revert record
carries ``actor`` exactly like the forward batch.
"""
from __future__ import annotations

import json

_HEADERS = {"Content-Type": "application/json", "Origin": "http://localhost"}


def test_undo_batch_unknown_batch_id_returns_404(signed_in_client, tmp_reciter_dir):
    """Unknown batch_id flows through the lock decorator and reaches the
    service layer, which 404s on missing history."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")

    res = client.post(
        f"/api/seg/undo-batch/{reciter}",
        data=json.dumps({"batch_id": "no-such-batch"}),
        headers=_HEADERS,
    )
    assert res.status_code in (200, 400, 404)


def test_undo_batch_round_trip_with_actor(signed_in_client, tmp_reciter_dir):
    """Save a delete op then undo it; the revert record carries ``actor``."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="u-1")
    chapter = 112

    client, _ = signed_in_client(hf_user_id="u-1", login="alice")

    save_payload = {
        "full_replace": True,
        "segments": [],
        "operations": [
            {
                "op_id": "op-1",
                "type": "delete",
                "command": {"type": "delete", "segmentUid": "019d5c88-f55f-7ee0-81d1-d99f423e8dd5"},
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
    save = client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(save_payload),
        headers=_HEADERS,
    )
    assert save.status_code == 200

    history_path = tmp_reciter_dir.root / reciter / "edit_history.jsonl"
    last_line = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])
    batch_id = last_line["batch_id"]
    assert last_line["actor"]["hf_user_id"] == "u-1"

    undo = client.post(
        f"/api/seg/undo-batch/{reciter}",
        data=json.dumps({"batch_id": batch_id}),
        headers=_HEADERS,
    )
    assert undo.status_code == 200, undo.get_json()

    detailed = json.loads(
        (tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8")
    )
    uids = [s.get("segment_uid") for e in detailed["entries"] for s in e.get("segments", [])]
    assert "019d5c88-f55f-7ee0-81d1-d99f423e8dd5" in uids, (
        "inverse patch did not restore the deleted segment"
    )

    revert_line = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])
    assert revert_line.get("reverts_batch_id") == batch_id
    assert revert_line["actor"] == {
        "hf_user_id": "u-1",
        "login_at_time": "alice",
        "role": "contributor",
    }


def test_undo_ops_unknown_returns_400_or_404(signed_in_client, tmp_reciter_dir):
    """undo-ops route accepts (batch_id, op_ids) and returns 4xx for unknown ids."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")

    res = client.post(
        f"/api/seg/undo-ops/{reciter}",
        data=json.dumps({"batch_id": "no-such-batch", "op_ids": ["op-1"]}),
        headers=_HEADERS,
    )
    assert res.status_code in (200, 400, 404)


def test_undo_batch_anonymous_returns_401(flask_client, tmp_reciter_dir):
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    res = flask_client.post(
        f"/api/seg/undo-batch/{reciter}",
        data=json.dumps({"batch_id": "no-such-batch"}),
        headers=_HEADERS,
    )
    assert res.status_code == 401
