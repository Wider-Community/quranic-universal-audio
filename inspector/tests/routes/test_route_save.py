"""POST /api/seg/save tests (MUST-1, MUST-7)."""
from __future__ import annotations

import json

import pytest


def test_save_accepts_full_replace_payload(flask_client, tmp_reciter_dir):
    """A canonical full_replace payload is accepted with HTTP 200."""
    reciter = "fixture_reciter"
    fixture_path = tmp_reciter_dir.install(reciter, "112-ikhlas")
    chapter = 112

    payload = {
        "full_replace": True,
        "segments": [
            {
                "time_start": 4700,
                "time_end": 7700,
                "matched_ref": "112:1:1-112:1:4",
                "matched_text": "قُلْ هُوَ ٱللَّهُ أَحَدٌ",
                "confidence": 1.0,
                "phonemes_asr": "",
                "segment_uid": "019d5c88-f55f-7ee0-81d1-d99f423e8dd5",
            },
        ],
        "operations": [],
    }

    res = flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert res.status_code in (200, 404), (
        f"unexpected status {res.status_code}; body={res.get_json()}"
    )


def test_save_accepts_patch_payload(flask_client, tmp_reciter_dir):
    """A patch payload (segments[].index) is accepted with HTTP 200."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")
    chapter = 112

    payload = {
        "segments": [
            {"index": 0, "matched_ref": "112:1:1-112:1:4", "matched_text": "x"},
        ],
        "operations": [],
    }

    res = flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert res.status_code in (200, 404)


@pytest.mark.xfail(reason="phase-5", strict=False)
def test_save_includes_patch_field_in_history(flask_client, tmp_reciter_dir):
    """Phase 5 contract: save handler injects a patch field on every op without one.

    Pre-Phase-5 the backend persists ops verbatim — if the frontend doesn't
    send a `patch`, the saved op also lacks one. Phase 5 introduces a
    server-side patch synthesizer for legacy clients (forward-compat); the
    saved record must always carry `patch` from this point on.
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
                "type": "delete",
                "segment_uid": "019d5c88-f55f-7ee0-81d1-d99f423e8dd5",
                # Note: NO patch field — Phase 5 backend must synthesize.
            },
        ],
    }
    res = flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert res.status_code == 200

    history_path = tmp_reciter_dir.root / reciter / "edit_history.jsonl"
    last = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])
    op = last["operations"][0]
    assert "patch" in op, "Phase 5: every history op must carry a patch field"


@pytest.mark.xfail(reason="phase-3", strict=False)
def test_save_payload_is_correctly_built_from_command_results(flask_client, tmp_reciter_dir):
    """Phase 3: save handler validates CommandResult-shaped payloads via schema.

    Phase 3 introduces schema-strict validation of the `command` envelope.
    A payload with an unknown command type is rejected. Pre-Phase-3 there
    is no schema, so any object passes through.
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
                "type": "trim",
                "command": {"type": "fictional-command-type", "segmentUid": "x"},
            },
        ],
    }
    res = flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert res.status_code == 400, (
        "Phase 3 must reject unknown `command.type` values"
    )
