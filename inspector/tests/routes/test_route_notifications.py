"""``/api/me/notifications`` route coverage.

The rail is per-user, dismissable → archived, restorable. The contract that
matters: signed-in only, owner-scoped (you can't touch another user's rows),
list marks seen (clearing the unread badge), dismiss/restore move between
active⇄archive, and ``/api/me`` surfaces the unread count.

Notifications are seeded through ``repo_notifications.create`` inside a durable
transaction (the same boundary the emitter uses) — never hand-INSERTed.
"""

from __future__ import annotations

import json

from services.db import repo_notifications
from services.db import sync as _sync

_ORIGIN = {"Origin": "http://localhost"}


def _seed(hf_user_id, source_key, *, title="Your request for X was sent back", body=None):
    with _sync.durable_transaction():
        repo_notifications.create(
            hf_user_id=hf_user_id,
            event="reciter.request_rejected_soft",
            slug="x",
            title=title,
            body=body,
            payload=None,
            source_key=source_key,
        )


def test_list_requires_sign_in(flask_client):
    assert flask_client.get("/api/me/notifications").status_code == 401


def test_dismiss_requires_sign_in(flask_client):
    assert flask_client.post("/api/me/notifications/1/dismiss", headers=_ORIGIN).status_code == 401


def test_list_returns_active_with_unread(signed_in_client):
    client, _ = signed_in_client(hf_user_id="n-1", login="alice")
    _seed("n-1", "src-a")
    _seed("n-1", "src-b")

    body = json.loads(client.get("/api/me/notifications").data)
    assert len(body["notifications"]) == 2
    assert body["unread"] == 2


def test_list_marks_seen_so_second_call_has_zero_unread(signed_in_client):
    client, _ = signed_in_client(hf_user_id="n-2", login="bob")
    _seed("n-2", "src-a")

    first = json.loads(client.get("/api/me/notifications").data)
    assert first["unread"] == 1
    second = json.loads(client.get("/api/me/notifications").data)
    assert second["unread"] == 0
    assert len(second["notifications"]) == 1  # still active, just seen


def test_me_surfaces_unread_count(signed_in_client):
    client, _ = signed_in_client(hf_user_id="n-3", login="carol")
    _seed("n-3", "src-a")
    me = json.loads(client.get("/api/me").data)
    assert me["notifications_unread"] == 1


def test_dismiss_moves_to_archive(signed_in_client):
    client, _ = signed_in_client(hf_user_id="n-4", login="dave")
    _seed("n-4", "src-a")
    nid = json.loads(client.get("/api/me/notifications").data)["notifications"][0]["id"]

    assert client.post(f"/api/me/notifications/{nid}/dismiss", headers=_ORIGIN).status_code == 204

    active = json.loads(client.get("/api/me/notifications").data)["notifications"]
    archived = json.loads(client.get("/api/me/notifications/archived").data)["notifications"]
    assert active == []
    assert len(archived) == 1 and archived[0]["id"] == nid


def test_restore_returns_to_active(signed_in_client):
    client, _ = signed_in_client(hf_user_id="n-5", login="erin")
    _seed("n-5", "src-a")
    nid = json.loads(client.get("/api/me/notifications").data)["notifications"][0]["id"]
    client.post(f"/api/me/notifications/{nid}/dismiss", headers=_ORIGIN)

    assert client.post(f"/api/me/notifications/{nid}/restore", headers=_ORIGIN).status_code == 204
    active = json.loads(client.get("/api/me/notifications").data)["notifications"]
    assert len(active) == 1 and active[0]["id"] == nid


def test_dismiss_is_owner_scoped(signed_in_client):
    """User B can't dismiss user A's notification — 404, and A's row survives."""
    client_a, _ = signed_in_client(hf_user_id="n-a", login="amy")
    _seed("n-a", "src-a")
    nid = json.loads(client_a.get("/api/me/notifications").data)["notifications"][0]["id"]

    client_b, _ = signed_in_client(hf_user_id="n-b", login="ben")
    assert client_b.post(f"/api/me/notifications/{nid}/dismiss", headers=_ORIGIN).status_code == 404

    still_active = json.loads(client_a.get("/api/me/notifications").data)["notifications"]
    assert len(still_active) == 1


def test_dismiss_unknown_id_is_404(signed_in_client):
    client, _ = signed_in_client(hf_user_id="n-6", login="finn")
    assert client.post("/api/me/notifications/99999/dismiss", headers=_ORIGIN).status_code == 404
