"""Backend mirror tests for the command/apply-command surface (IS-5).

Most of the command logic lives on the frontend; the backend ensures save
acceptance + history record produces matching shapes.
"""
from __future__ import annotations

import json

import pytest


def test_save_payload_carries_op_log_in_canonical_shape(flask_client, tmp_reciter_dir):
    """Save payload includes a per-op `command` envelope describing the discriminated union.

    Phase 3 introduces the `command` field on each operation (the
    SegmentCommand union literal). The backend must accept and persist
    this field on the history record.
    """
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    chapter = 112

    payload = {
        "full_replace": True,
        "segments": [],
        "operations": [
            {
                "op_id": "op-trim-1",
                "type": "trim",
                "command": {
                    "type": "trim",
                    "segmentUid": "019d5c88-f55f-7ee0-81d1-d99f423e8dd5",
                    "delta": {"time_start": 4710},
                },
                "snapshots": {"before": {"time_start": 4700}, "after": {"time_start": 4710}},
                "affected_chapters": [chapter],
            }
        ],
    }
    res = flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert res.status_code == 200

    history_path = tmp_reciter_dir.root / reciter / "edit_history.jsonl"
    record = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])
    op = record["operations"][0]
    assert "command" in op, "Phase 3 contract: each op carries a `command` envelope"
    assert op["command"]["type"] == "trim"
    assert "segmentUid" in op["command"]


def test_history_record_reflects_command_result_metadata(flask_client, tmp_reciter_dir):
    """Save handler rejects ops that lack a ``command`` envelope.

    Every operation in the save payload must carry a ``command`` object
    whose ``type`` matches the enclosing ``op.type``.  A payload with a
    missing ``command`` key must be rejected with HTTP 400.
    """
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    chapter = 112

    payload = {
        "full_replace": True,
        "segments": [],
        "operations": [
            {
                "op_id": "op-1",
                "type": "merge",
            }
        ],
    }
    res = flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert res.status_code == 400, (
        "Phase 3 must reject save payloads whose ops lack a `command` envelope"
    )
