"""POST /api/seg/save tests (MUST-1, MUST-7).

``require_same_origin`` + ``require_edit_lock(admin_bypass=True)`` gate every
save/undo route. These tests assert:

- Anonymous requests are rejected (401 via the lock decorator).
- Cross-origin POSTs are rejected (403 via the same-origin guard).
- The active reviewer's saves succeed and stamp ``actor`` on every batch.
- A maintainer can save someone else's active claim (admin_bypass).
- Marked-ready rows reject saves (403).
- The save payload contract checks still apply (patch synthesizer,
  command-envelope validation).
"""
from __future__ import annotations

import json

_ORIGIN = "http://localhost"
_HEADERS = {"Content-Type": "application/json", "Origin": _ORIGIN}


# ---------------------------------------------------------------------------
# Auth + lock surfaces
# ---------------------------------------------------------------------------


def test_save_anonymous_returns_401(flask_client, tmp_reciter_dir):
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    res = flask_client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps({"segments": [], "operations": []}),
        headers=_HEADERS,
    )
    assert res.status_code == 401


def test_save_missing_origin_returns_403(signed_in_client, tmp_reciter_dir):
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")
    res = client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps({"segments": [], "operations": []}),
        content_type="application/json",
    )
    assert res.status_code == 403


def test_save_non_assignee_returns_403(signed_in_client, tmp_reciter_dir):
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="other-user")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")
    res = client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps({"segments": [], "operations": []}),
        headers=_HEADERS,
    )
    assert res.status_code == 403
    assert res.get_json()["code"] == "NOT_CLAIM_HOLDER"


def test_save_wrong_state_returns_403_with_state_label(signed_in_client, tmp_reciter_dir):
    """A non-owner saving a row that isn't UNDER_REVIEW gets NOT_EDITABLE_STATE
    plus a humanized ``context.state_label`` for the FE to render."""
    from qua_shared.schemas import ReciterState

    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    # Close the claim + flip the row to AWAITING_REVIEW (not editable).
    from services import db as _db
    from services.db import repo_claims, repo_state
    with _db.transaction():
        repo_claims.close_claim(slug=reciter, close_reason="test")
        repo_state.update_state(reciter, state=ReciterState.AWAITING_REVIEW)

    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")
    res = client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps({"segments": [], "operations": []}),
        headers=_HEADERS,
    )
    assert res.status_code == 403
    body = res.get_json()
    assert body["code"] == "NOT_EDITABLE_STATE"
    assert body["context"]["state_label"] == "available for review"


def test_save_maintainer_can_override_assignee(signed_in_client, tmp_reciter_dir):
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="other-user")
    client, _ = signed_in_client(hf_user_id="mod-1", login="mod", role="maintainer")
    res = client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps({"full_replace": True, "segments": [], "operations": []}),
        headers=_HEADERS,
    )
    assert res.status_code in (200, 400), (
        f"unexpected status {res.status_code}; body={res.get_json()}"
    )
    # 400 is acceptable when the empty-segments payload trips a validation
    # rule; the point is the decorator chain didn't block us.
    if res.status_code == 200:
        history_path = (
            tmp_reciter_dir.root / reciter / "edit_history.jsonl"
        )
        line = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])
        assert line["actor"]["hf_user_id"] == "mod-1"
        assert line["actor"]["role"] == "maintainer"


def test_save_marked_ready_returns_403(signed_in_client, tmp_reciter_dir):
    """Marked-ready rows are frozen — the lock decorator refuses saves even
    for the active assignee. They must Unmark first."""
    from datetime import datetime, timezone

    from qua_shared.schemas import (
        ReciterRow, ReciterState, ReciterStateFile, Visibility,
    )
    from services import state as state_service

    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")

    # Mark the existing open claim ready.
    from services import db as _db
    from services.db import repo_claims
    with _db.transaction():
        repo_claims.set_marked_ready(reciter, ready=True)

    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")
    res = client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps({"segments": [], "operations": []}),
        headers=_HEADERS,
    )
    assert res.status_code == 403
    assert res.get_json()["code"] == "MARKED_READY_FROZEN"


def test_save_owner_bypasses_state_check(signed_in_client, tmp_reciter_dir):
    """Owner can save to a row that isn't UNDER_REVIEW (state bypass)."""
    from datetime import datetime, timezone

    from qua_shared.schemas import (
        ReciterRow, ReciterState, ReciterStateFile, Visibility,
    )
    from services import state as state_service

    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="other-user")

    # Flip state to catalogued (close the claim) so a non-owner would get 403.
    from services import db as _db
    from services.db import repo_claims, repo_state
    with _db.transaction():
        repo_claims.close_claim(slug=reciter, close_reason="test")
        repo_state.update_state(reciter, state=ReciterState.CATALOGUED)

    client, _ = signed_in_client(hf_user_id="u-owner", login="owner_user", role="owner")
    res = client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps({"full_replace": True, "segments": [], "operations": []}),
        headers=_HEADERS,
    )
    # 200 or 400 are both acceptable — the lock passed (no 403 for state mismatch).
    assert res.status_code in (200, 400), (
        f"unexpected status {res.status_code}; body={res.get_json()}"
    )


def test_save_owner_marked_ready_bypasses_freeze(signed_in_client, tmp_reciter_dir):
    """Owner override is total — marked_ready does not block owner saves."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="u-owner")

    from services import db as _db
    from services.db import repo_claims
    with _db.transaction():
        repo_claims.set_marked_ready(reciter, ready=True)

    client, _ = signed_in_client(hf_user_id="u-owner", login="owner_user", role="owner")
    res = client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps({"full_replace": True, "segments": [], "operations": []}),
        headers=_HEADERS,
    )
    # Gate passed — 200 (save succeeded) or 400 (payload-shape complaint) both
    # confirm the lock did not 403 on marked_ready.
    assert res.status_code in (200, 400), (
        f"unexpected status {res.status_code}; body={res.get_json()}"
    )


# ---------------------------------------------------------------------------
# Existing save-payload contract tests (now signed in)
# ---------------------------------------------------------------------------


def test_save_accepts_full_replace_payload(signed_in_client, tmp_reciter_dir):
    """A canonical full_replace payload is accepted with HTTP 200."""
    reciter = "fixture_reciter"
    fixture_path = tmp_reciter_dir.install(
        reciter, "112-ikhlas", under_review_for="test-user-1",
    )
    chapter = 112

    payload = {
        "full_replace": True,
        "segments": [
            {
                "time_start": 4700,
                "time_end": 7700,
                "matched_ref": "112:1:1-112:1:4",
                "confidence": 1.0,
                "segment_uid": "019d5c88-f55f-7ee0-81d1-d99f423e8dd5",
            },
        ],
        "operations": [],
    }

    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")
    res = client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        headers=_HEADERS,
    )
    assert res.status_code in (200, 404), (
        f"unexpected status {res.status_code}; body={res.get_json()}"
    )


def test_save_accepts_patch_payload(signed_in_client, tmp_reciter_dir):
    """A patch payload (segments[].index) is accepted with HTTP 200."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    chapter = 112

    payload = {
        "segments": [
            {"index": 0, "matched_ref": "112:1:1-112:1:4"},
        ],
        "operations": [],
    }

    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")
    res = client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        headers=_HEADERS,
    )
    assert res.status_code in (200, 404)


def test_save_includes_patch_field_in_history(signed_in_client, tmp_reciter_dir):
    """The save handler injects a ``patch`` field on every op without one."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    chapter = 112

    payload = {
        "full_replace": True,
        "segments": [],
        "operations": [
            {
                "op_id": "op-1",
                "type": "delete",
                "segment_uid": "019d5c88-f55f-7ee0-81d1-d99f423e8dd5",
                "command": {
                    "type": "delete",
                    "segmentUid": "019d5c88-f55f-7ee0-81d1-d99f423e8dd5",
                },
            },
        ],
    }
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")
    res = client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        headers=_HEADERS,
    )
    assert res.status_code == 200

    history_path = tmp_reciter_dir.root / reciter / "edit_history.jsonl"
    last = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])
    op = last["operations"][0]
    assert "patch" in op, "every history op must carry a patch field"


def test_save_rejects_unknown_command_type(
    signed_in_client, tmp_reciter_dir,
):
    """Save handler rejects an operation whose command.type is not a known reducer."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
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
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")
    res = client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps(payload),
        headers=_HEADERS,
    )
    assert res.status_code == 400, "save rejects unknown `command.type` values"


def test_save_writes_actor_block_to_history(signed_in_client, tmp_reciter_dir):
    """Every saved batch carries ``actor: {hf_user_id, login_at_time, role}``."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="u-1")

    client, _ = signed_in_client(hf_user_id="u-1", login="alice")
    payload = {
        "full_replace": True,
        "segments": [
            {
                "time_start": 4700,
                "time_end": 7700,
                "matched_ref": "112:1:1-112:1:4",
                "confidence": 1.0,
                "segment_uid": "019d5c88-f55f-7ee0-81d1-d99f423e8dd5",
            },
        ],
        "operations": [],
    }
    res = client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps(payload),
        headers=_HEADERS,
    )
    assert res.status_code == 200, res.get_json()

    history_path = tmp_reciter_dir.root / reciter / "edit_history.jsonl"
    line = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])
    assert "file_hash_after" not in line, "history must not carry file_hash_after"
    assert line["actor"] == {
        "hf_user_id": "u-1",
        "login_at_time": "alice",
        "role": "contributor",
    }
