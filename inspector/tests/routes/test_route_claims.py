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


def _stub_persist(monkeypatch):
    """Stop _persist_row from trying to hit a bucket backend during tests."""
    from services import state as state_service

    monkeypatch.setattr(
        state_service,
        "_persist_row",
        lambda row, *, replace_existing: None,
    )
    # ``state.transition`` also calls ``audit.append`` after the handler;
    # stub it so the test doesn't touch the audit storage backend either.
    from services import audit as audit_service

    monkeypatch.setattr(audit_service, "append", lambda **kw: None)


# ---------------------------------------------------------------------------
# claim
# ---------------------------------------------------------------------------


def test_claim_anonymous_returns_401(flask_client, monkeypatch):
    _stub_persist(monkeypatch)
    _replace_state([_row("test_slug", state="awaiting_review")])
    resp = flask_client.post(
        "/api/claim/test_slug",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 401


def test_claim_happy_path(signed_in_client, monkeypatch):
    _stub_persist(monkeypatch)
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


def test_claim_one_claim_per_user_returns_409(signed_in_client, monkeypatch):
    _stub_persist(monkeypatch)
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


def test_claim_discarded_returns_400(signed_in_client, monkeypatch):
    _stub_persist(monkeypatch)
    _replace_state([_row("test_slug", state="awaiting_review", visibility="discarded")])

    client, _ = signed_in_client(hf_user_id="u-1", login="alice")
    resp = client.post(
        "/api/claim/test_slug",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 400


def test_claim_already_under_review_returns_400(signed_in_client, monkeypatch):
    _stub_persist(monkeypatch)
    _replace_state([_row("test_slug", state="under_review", assignee_hf_id="other-user")])

    client, _ = signed_in_client(hf_user_id="u-1", login="alice")
    resp = client.post(
        "/api/claim/test_slug",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 400


def test_claim_missing_origin_returns_403(signed_in_client, monkeypatch):
    """CSRF defense — POST without matching Origin/Referer is rejected."""
    _stub_persist(monkeypatch)
    _replace_state([_row("test_slug", state="awaiting_review")])

    client, _ = signed_in_client(hf_user_id="u-1", login="alice")
    resp = client.post("/api/claim/test_slug")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# release
# ---------------------------------------------------------------------------


def test_release_happy_path(signed_in_client, monkeypatch):
    _stub_persist(monkeypatch)
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


def test_release_non_assignee_returns_403(signed_in_client, monkeypatch):
    _stub_persist(monkeypatch)
    _replace_state([_row("test_slug", state="under_review", assignee_hf_id="other")])

    client, _ = signed_in_client(hf_user_id="u-1", login="alice")
    resp = client.post(
        "/api/release/test_slug",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 403


def test_release_maintainer_can_force_release(signed_in_client, monkeypatch):
    """Maintainers can release someone else's claim through the normal
    release route (the dedicated force-release endpoint with reason
    lands in Phase 4)."""
    _stub_persist(monkeypatch)
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


def test_mark_unmark_round_trip(signed_in_client, monkeypatch):
    _stub_persist(monkeypatch)
    _replace_state([_row("test_slug", state="under_review", assignee_hf_id="u-1")])

    client, _ = signed_in_client(hf_user_id="u-1", login="alice")

    resp1 = client.post(
        "/api/mark-ready/test_slug",
        headers={"Origin": "http://localhost"},
    )
    assert resp1.status_code == 200
    assert json.loads(resp1.data)["marked_ready"] is True

    # Reseed: state-machine doesn't actually mutate _state_file because we
    # stubbed _persist_row; the handler returns the new row but state_store
    # stays the same. So manually flip marked_ready=True before unmark.
    _replace_state([_row(
        "test_slug",
        state="under_review",
        assignee_hf_id="u-1",
        marked_ready=True,
    )])

    resp2 = client.post(
        "/api/unmark-ready/test_slug",
        headers={"Origin": "http://localhost"},
    )
    assert resp2.status_code == 200
    assert json.loads(resp2.data)["marked_ready"] is False


def test_mark_ready_non_assignee_returns_403(signed_in_client, monkeypatch):
    _stub_persist(monkeypatch)
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
