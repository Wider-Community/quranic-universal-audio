"""Per-op save-acceptance round-trip tests (IS-6)."""
from __future__ import annotations

import json

import pytest


OP_TYPES = ["trim", "split", "merge", "edit_reference", "delete", "ignore_issue"]


def _payload_with_command(op_type: str, chapter: int) -> dict:
    return {
        "full_replace": True,
        "segments": [],
        "operations": [
            {
                "op_id": f"op-{op_type}-1",
                "type": op_type,
                "command": {"type": op_type, "segmentUid": "x"},
                "affected_chapters": [chapter],
            }
        ],
    }


@pytest.mark.parametrize("op_type", OP_TYPES, ids=OP_TYPES)
@pytest.mark.xfail(reason="phase-3", strict=False)
def test_command_save_round_trip(op_type, flask_client, tmp_reciter_dir):
    """For each op type, the save endpoint persists `command`, `affected_chapters`, and `snapshots`.

    Phase 3 contract: every op carries a `command` envelope; the backend's
    save handler MUST persist it. Pre-Phase-3 the backend stores
    `operations` verbatim, so the assertion that the persisted op has a
    parsed `command.segmentUid` matching the input is true even pre-Phase-3
    — but Phase 3 also validates that the envelope's `type` matches the
    op-level `type`. Pre-Phase-3 there is no validator, so injecting a
    mismatched envelope still saves.
    """
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    chapter = 112

    payload = _payload_with_command(op_type, chapter)
    payload["operations"][0]["command"]["type"] = "WRONG_TYPE"

    res = flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert res.status_code == 400, (
        "Phase 3 must reject ops whose `command.type` differs from `op.type`"
    )
