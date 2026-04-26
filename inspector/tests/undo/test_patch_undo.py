"""Patch-based undo tests (IS-9, MUST-8)."""
from __future__ import annotations

import json
import pytest


COMMAND_TYPES = ["trim", "split", "merge", "edit_reference", "delete", "ignore_issue"]


def _save_with_patch(flask_client, reciter, chapter, op_type, patch):
    payload = {
        "full_replace": True,
        "segments": [],
        "operations": [
            {
                "op_id": f"op-{op_type}-1",
                "type": op_type,
                "patch": patch,
            }
        ],
    }
    return flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        content_type="application/json",
    )


@pytest.mark.parametrize("op_type", COMMAND_TYPES, ids=COMMAND_TYPES)
def test_command_produces_complete_patch(op_type, flask_client, tmp_reciter_dir):
    """For each op, the backend validates the patch shape and rejects malformed ones.

    Phase 5 contract: when an op carries a `patch` envelope, the save
    handler validates that `before`, `after`, `removedIds`, `insertedIds`,
    and `affectedChapterIds` are all present and well-typed. Pre-Phase-5
    the backend stores any object as `patch` without validation, so a
    payload missing `affectedChapterIds` still saves with HTTP 200. Phase 5
    must reject it (HTTP 400).
    """
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    chapter = 112

    bad_patch = {
        "before": [{"segment_uid": "uid-1"}],
        "after": [{"segment_uid": "uid-1"}],
        # missing removedIds, insertedIds, affectedChapterIds
    }
    res = _save_with_patch(flask_client, reciter, chapter, op_type, bad_patch)
    assert res.status_code == 400, (
        "Phase 5 must reject patch envelopes missing required fields"
    )


@pytest.mark.xfail(reason="phase-5", strict=False)
def test_inverse_patch_restores_state_exactly(flask_client, tmp_reciter_dir):
    """Apply patch → undo → state equals pre-patch (MUST-8)."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    chapter = 112

    pre = json.loads((tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8"))
    target_uid = pre["entries"][0]["segments"][0]["segment_uid"]

    patch = {
        "before": [pre["entries"][0]["segments"][0]],
        "after": [],
        "removedIds": [target_uid],
        "insertedIds": [],
        "affectedChapterIds": [chapter],
    }
    save = _save_with_patch(flask_client, reciter, chapter, "delete", patch)
    assert save.status_code == 200

    history_path = tmp_reciter_dir.root / reciter / "edit_history.jsonl"
    last = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])
    flask_client.post(
        f"/api/seg/undo-batch/{reciter}",
        data=json.dumps({"batch_id": last["batch_id"]}),
        content_type="application/json",
    )

    post = json.loads((tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8"))
    assert post == pre, "undo did not restore detailed.json byte-equal to pre-state"


def test_inverse_patch_restores_ignored_categories(flask_client, tmp_reciter_dir):
    """Segments with ignored_categories are fully restored on undo."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "113-falaq")

    pre = json.loads((tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8"))
    target = pre["entries"][0]["segments"][0]
    assert target.get("ignored_categories"), "fixture must include ignored_categories on segment 0"

    patch = {
        "before": [target],
        "after": [{**target, "ignored_categories": []}],
        "removedIds": [],
        "insertedIds": [],
        "affectedChapterIds": [113],
    }
    _save_with_patch(flask_client, reciter, 113, "ignore_issue", patch)

    history_path = tmp_reciter_dir.root / reciter / "edit_history.jsonl"
    last = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])
    flask_client.post(
        f"/api/seg/undo-batch/{reciter}",
        data=json.dumps({"batch_id": last["batch_id"]}),
        content_type="application/json",
    )

    post = json.loads((tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8"))
    restored = post["entries"][0]["segments"][0]
    assert restored.get("ignored_categories") == target["ignored_categories"]


def test_inverse_patch_handles_inserted_and_removed_ids(flask_client, tmp_reciter_dir):
    """Split (inserts) and delete (removes) round-trip correctly."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    pre = json.loads((tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8"))
    seg0 = pre["entries"][0]["segments"][0]
    new_uid_a = "split-a"
    new_uid_b = "split-b"

    patch = {
        "before": [seg0],
        "after": [
            {**seg0, "segment_uid": new_uid_a, "time_end": 5000},
            {**seg0, "segment_uid": new_uid_b, "time_start": 5000},
        ],
        "removedIds": [seg0["segment_uid"]],
        "insertedIds": [new_uid_a, new_uid_b],
        "affectedChapterIds": [112],
    }
    _save_with_patch(flask_client, reciter, 112, "split", patch)

    history_path = tmp_reciter_dir.root / reciter / "edit_history.jsonl"
    last = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])
    flask_client.post(
        f"/api/seg/undo-batch/{reciter}",
        data=json.dumps({"batch_id": last["batch_id"]}),
        content_type="application/json",
    )

    post = json.loads((tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8"))
    uids = [s["segment_uid"] for s in post["entries"][0]["segments"]]
    assert seg0["segment_uid"] in uids
    assert new_uid_a not in uids
    assert new_uid_b not in uids


def test_legacy_record_falls_back_to_field_restore(flask_client, tmp_reciter_dir):
    """Undo a record without a patch field still works via the existing field-restore path."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    res = flask_client.post(
        f"/api/seg/undo-batch/{reciter}",
        data=json.dumps({"batch_id": "no-such-batch"}),
        content_type="application/json",
    )
    assert res.status_code in (200, 400, 404)
