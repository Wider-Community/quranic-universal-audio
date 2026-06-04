"""Per-op save-acceptance round-trip tests (IS-6)."""
from __future__ import annotations

import json

import pytest


_HEADERS = {"Content-Type": "application/json", "Origin": "http://localhost"}

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
def test_save_rejects_command_type_mismatch(op_type, signed_in_client, tmp_reciter_dir):
    """Save handler rejects ops whose ``command.type`` does not match ``op.type``.

    Every operation must carry a ``command`` envelope and its ``type``
    must match the enclosing ``op.type``.  A mismatched type must be
    rejected with HTTP 400; a correct type must be persisted in the
    history record.
    """
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")
    chapter = 112

    payload = _payload_with_command(op_type, chapter)
    payload["operations"][0]["command"]["type"] = "WRONG_TYPE"

    res = client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        headers=_HEADERS,
    )
    assert res.status_code == 400, (
        "save must reject ops whose `command.type` differs from `op.type`"
    )
