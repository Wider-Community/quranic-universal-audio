"""Claim / release / mark-ready / unmark-ready + reciter-task route tests.

The state-machine handlers in ``services/state.py`` already have their own
unit coverage; these tests exercise the HTTP boundary:

- happy paths return 200 with the new authoritative row
- one-claim-per-user policy returns 409 ``existing_claim``
- state-machine rejections surface as 400 / 403 / 404 via app errorhandlers
- predicates flip correctly across contributor / maintainer / anonymous
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

os.environ.setdefault("INSPECTOR_SESSION_SECRET", "0" * 64)


def _replace_state(rows: list):
    from scripts.lib.schemas import ReciterStateFile
    from services import state as state_service

    new_file = ReciterStateFile(reciters=rows)
    with state_service._state_lock:  # type: ignore[attr-defined]
        state_service._state_file = new_file  # type: ignore[attr-defined]


def _row(slug: str, *, state: str = "awaiting_review",
         assignee_hf_id: str | None = None,
         marked_ready: bool = False,
         visibility: str = "public"):
    from scripts.lib.schemas import ReciterRow, ReciterState, Visibility

    return ReciterRow(
        slug=slug,
        state=ReciterState(state),
        state_since=datetime.now(timezone.utc),
        assignee_hf_id=assignee_hf_id,
        assignee_login="prev_owner" if assignee_hf_id else None,
        assignee_since=datetime.now(timezone.utc) if assignee_hf_id else None,
        marked_ready=marked_ready,
        visibility=Visibility(visibility),
    )


# NOTE: claim/release/mark-ready tests use the `state_persistence` fixture
# (defined in tests/conftest.py) so state transitions persist through a real
# FilesystemBackend. The legacy `_stub_persist` mock pattern stripped both the
# bucket write AND the in-memory _state_file update, forcing each test to
# manually re-seed state between requests; real persistence makes that hack
# unnecessary and exercises the actual write/read seam that production hits.


# ---------------------------------------------------------------------------
# claim
# ---------------------------------------------------------------------------


def test_claim_anonymous_returns_401(flask_client, state_persistence):
    _replace_state([_row("test_slug", state="awaiting_review")])
    resp = flask_client.post(
        "/api/claim/test_slug",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 401


def test_claim_happy_path(signed_in_client, state_persistence):
    _replace_state([_row("test_slug", state="awaiting_review")])

    client, user = signed_in_client(hf_user_id="u-1", login="alice")
    resp = client.post(
        "/api/claim/test_slug",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body["state"] == "under_review"
    assert body["assignee_hf_id"] == "u-1"
    assert body["assignee_login"] == "alice"


def test_claim_persists_across_requests(signed_in_client, state_persistence):
    """Claim → second request sees the new state without manual re-seed.

    Catches the class of regressions where _persist_row drops a write
    silently — the legacy `_stub_persist` fixture masked this because it
    skipped persistence entirely AND required tests to re-seed state
    manually between requests.
    """
    _replace_state([_row("test_slug", state="awaiting_review")])

    client, _ = signed_in_client(hf_user_id="u-1", login="alice")
    resp1 = client.post(
        "/api/claim/test_slug",
        headers={"Origin": "http://localhost"},
    )
    assert resp1.status_code == 200

    # Second request reads the post-claim state from _state_file.
    resp2 = client.get("/api/reciter-task/test_slug")
    assert resp2.status_code == 200
    body = json.loads(resp2.data)
    assert body["row"]["state"] == "under_review"
    assert body["row"]["assignee_hf_id"] == "u-1"
    # Predicates flipped correctly for the claimant.
    assert body["predicates"]["can_release"] is True
    assert body["predicates"]["can_claim"] is False  # already holds


def test_claim_one_claim_per_user_returns_409(signed_in_client, state_persistence):
    _replace_state([
        _row("other", state="under_review", assignee_hf_id="u-1"),
        _row("target", state="awaiting_review"),
    ])

    client, _ = signed_in_client(hf_user_id="u-1", login="alice")
    resp = client.post(
        "/api/claim/target",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 409
    body = json.loads(resp.data)
    assert body["existing_claim"] == "other"
    # Slice 0 (Phase 6 pre-cleanup): 409 body must carry display names so the
    # toast can render "Unclaim <name>..." rather than slug strings. When the
    # test catalog is empty (typical for unit tests) display_name returns
    # None — the field is present but None, which the frontend falls back
    # to the raw slug. See `inspector/services/catalog.display_name`.
    assert "existing_claim_name" in body
    assert "target_name" in body


def test_claim_discarded_returns_400(signed_in_client, state_persistence):
    _replace_state([_row("test_slug", state="awaiting_review", visibility="discarded")])

    client, _ = signed_in_client(hf_user_id="u-1", login="alice")
    resp = client.post(
        "/api/claim/test_slug",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 400


def test_claim_already_under_review_returns_400(signed_in_client, state_persistence):
    _replace_state([_row("test_slug", state="under_review", assignee_hf_id="other-user")])

    client, _ = signed_in_client(hf_user_id="u-1", login="alice")
    resp = client.post(
        "/api/claim/test_slug",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 400


def test_claim_missing_origin_returns_403(signed_in_client, state_persistence):
    """CSRF defense — POST without matching Origin/Referer is rejected."""
    _replace_state([_row("test_slug", state="awaiting_review")])

    client, _ = signed_in_client(hf_user_id="u-1", login="alice")
    resp = client.post("/api/claim/test_slug")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# release
# ---------------------------------------------------------------------------


def test_release_happy_path(signed_in_client, state_persistence):
    _replace_state([_row("test_slug", state="under_review", assignee_hf_id="u-1")])

    client, _ = signed_in_client(hf_user_id="u-1", login="alice")
    resp = client.post(
        "/api/release/test_slug",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body["state"] == "awaiting_review"
    assert body["assignee_hf_id"] is None


def test_release_non_assignee_returns_403(signed_in_client, state_persistence):
    _replace_state([_row("test_slug", state="under_review", assignee_hf_id="other")])

    client, _ = signed_in_client(hf_user_id="u-1", login="alice")
    resp = client.post(
        "/api/release/test_slug",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 403


def test_release_maintainer_can_force_release(signed_in_client, state_persistence):
    """Maintainers can release someone else's claim through the normal
    release route (the dedicated force-release endpoint with reason
    lands in Phase 4)."""
    _replace_state([_row("test_slug", state="under_review", assignee_hf_id="other")])

    client, _ = signed_in_client(hf_user_id="u-mod", login="mod", role="maintainer")
    resp = client.post(
        "/api/release/test_slug",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# mark-ready / unmark-ready
# ---------------------------------------------------------------------------


def test_mark_unmark_round_trip(signed_in_client, state_persistence):
    _replace_state([_row("test_slug", state="under_review", assignee_hf_id="u-1")])

    client, _ = signed_in_client(hf_user_id="u-1", login="alice")

    resp1 = client.post(
        "/api/mark-ready/test_slug",
        headers={"Origin": "http://localhost"},
    )
    assert resp1.status_code == 200
    assert json.loads(resp1.data)["marked_ready"] is True

    # State persists across requests via the FilesystemBackend, so the
    # mark_ready=True flip from resp1 is already in _state_file when we hit
    # unmark-ready below — no manual reseed needed.

    resp2 = client.post(
        "/api/unmark-ready/test_slug",
        headers={"Origin": "http://localhost"},
    )
    assert resp2.status_code == 200
    assert json.loads(resp2.data)["marked_ready"] is False


def test_mark_ready_non_assignee_returns_403(signed_in_client, state_persistence):
    _replace_state([_row("test_slug", state="under_review", assignee_hf_id="other")])

    client, _ = signed_in_client(hf_user_id="u-1", login="alice")
    resp = client.post(
        "/api/mark-ready/test_slug",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# reciter-task
# ---------------------------------------------------------------------------


def test_reciter_task_404_for_unknown_slug(flask_client):
    _replace_state([])
    resp = flask_client.get("/api/reciter-task/nope")
    assert resp.status_code == 404


def test_reciter_task_predicates_anonymous(flask_client):
    _replace_state([_row("test_slug", state="awaiting_review")])
    resp = flask_client.get("/api/reciter-task/test_slug")
    assert resp.status_code == 200
    body = json.loads(resp.data)
    preds = body["predicates"]
    # Anonymous → every contribution predicate is False
    assert preds == {
        "can_claim": False,
        "can_edit": False,
        "can_edit_as_admin": False,
        "can_edit_as_owner": False,
        "can_mark_ready": False,
        "can_unmark_ready": False,
        "can_release": False,
    }


def test_reciter_task_predicates_assignee(signed_in_client):
    _replace_state([_row("test_slug", state="under_review", assignee_hf_id="u-1")])
    client, _ = signed_in_client(hf_user_id="u-1", login="alice")
    resp = client.get("/api/reciter-task/test_slug")
    body = json.loads(resp.data)
    preds = body["predicates"]
    assert preds["can_edit"] is True
    assert preds["can_mark_ready"] is True
    assert preds["can_release"] is True
    assert preds["can_claim"] is False  # already holds; not awaiting_review


def test_reciter_task_predicates_maintainer_can_edit_as_admin(signed_in_client):
    _replace_state([_row("test_slug", state="under_review", assignee_hf_id="other")])
    client, _ = signed_in_client(hf_user_id="u-mod", login="mod", role="maintainer")
    resp = client.get("/api/reciter-task/test_slug")
    body = json.loads(resp.data)
    preds = body["predicates"]
    assert preds["can_edit"] is False  # not assignee
    assert preds["can_edit_as_admin"] is True
    assert preds["can_release"] is False  # not assignee on plain release
    # Mark-ready/unmark-ready still gated to assignee in Phase 3.
    assert preds["can_mark_ready"] is False


def test_reciter_task_predicates_one_claim_per_user(signed_in_client):
    _replace_state([
        _row("other", state="under_review", assignee_hf_id="u-1"),
        _row("target", state="awaiting_review"),
    ])
    client, _ = signed_in_client(hf_user_id="u-1", login="alice")
    resp = client.get("/api/reciter-task/target")
    body = json.loads(resp.data)
    assert body["predicates"]["can_claim"] is False  # has_other_active_claim


def test_reciter_task_predicates_marked_ready_frozen(signed_in_client):
    _replace_state([_row(
        "test_slug",
        state="under_review",
        assignee_hf_id="u-1",
        marked_ready=True,
    )])
    client, _ = signed_in_client(hf_user_id="u-1", login="alice")
    resp = client.get("/api/reciter-task/test_slug")
    preds = json.loads(resp.data)["predicates"]
    # Marked-ready means the row is frozen; can_edit/can_mark_ready are False.
    assert preds["can_edit"] is False
    assert preds["can_mark_ready"] is False
    assert preds["can_unmark_ready"] is True  # the affordance to thaw
    assert preds["can_release"] is True


# ---------------------------------------------------------------------------
# Owner-only permissions
# ---------------------------------------------------------------------------


def test_owner_can_claim_multiple_reciters(signed_in_client, state_persistence):
    """Owner bypasses the one-claim-per-user policy."""
    _replace_state([
        _row("already_claimed", state="under_review", assignee_hf_id="u-owner"),
        _row("second_target", state="awaiting_review"),
    ])
    client, _ = signed_in_client(hf_user_id="u-owner", login="owner_user", role="owner")
    resp = client.post(
        "/api/claim/second_target",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body["state"] == "under_review"
    assert body["assignee_hf_id"] == "u-owner"


def test_reciter_task_predicates_owner_can_edit_as_owner(signed_in_client):
    """Owner gets can_edit_as_owner=True on any public non-frozen row."""
    # Test with a catalogued row (state that normally blocks all edits)
    _replace_state([_row("test_slug", state="catalogued")])
    client, _ = signed_in_client(hf_user_id="u-owner", login="owner_user", role="owner")
    resp = client.get("/api/reciter-task/test_slug")
    preds = json.loads(resp.data)["predicates"]
    assert preds["can_edit_as_owner"] is True
    assert preds["can_edit"] is False  # not assignee
    assert preds["can_edit_as_admin"] is False  # not under_review


def test_reciter_task_predicates_owner_can_claim_with_other_active(signed_in_client):
    """Owner's can_claim is True even when they already hold another claim."""
    _replace_state([
        _row("held", state="under_review", assignee_hf_id="u-owner"),
        _row("target", state="awaiting_review"),
    ])
    client, _ = signed_in_client(hf_user_id="u-owner", login="owner_user", role="owner")
    resp = client.get("/api/reciter-task/target")
    preds = json.loads(resp.data)["predicates"]
    assert preds["can_claim"] is True


def test_reciter_task_predicates_owner_marked_ready_blocked(signed_in_client):
    """Owner cannot edit a marked_ready row (can_edit_as_owner is False)."""
    _replace_state([_row(
        "test_slug", state="under_review", assignee_hf_id="other", marked_ready=True,
    )])
    client, _ = signed_in_client(hf_user_id="u-owner", login="owner_user", role="owner")
    resp = client.get("/api/reciter-task/test_slug")
    preds = json.loads(resp.data)["predicates"]
    assert preds["can_edit_as_owner"] is False


def test_reciter_task_predicates_non_owner_lacks_can_edit_as_owner(signed_in_client):
    """Maintainer does not get can_edit_as_owner even on under_review rows."""
    _replace_state([_row("test_slug", state="under_review", assignee_hf_id="other")])
    client, _ = signed_in_client(hf_user_id="u-mod", login="mod", role="maintainer")
    resp = client.get("/api/reciter-task/test_slug")
    preds = json.loads(resp.data)["predicates"]
    assert preds["can_edit_as_owner"] is False
    assert preds["can_edit_as_admin"] is True  # still gets admin edit
