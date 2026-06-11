"""Announcement route coverage (admin compose/revoke + public read).

Contract:
- ``GET /api/announcements`` is public — anonymous visitors can read it (the
  whole point: announcements reach signed-out users).
- Composing / revoking gate on ``announcements.send`` (owner-only default):
  owner passes, maintainer/contributor are 403, anonymous is 401.
- A revoked announcement drops off the public list.
- The compose body is validated (empty title → 400).

Rows are created through the route (the boundary the UI uses), then read back to
verify the durability effect — never asserted via a mock.
"""

from __future__ import annotations

import json

_ORIGIN = {"Origin": "http://localhost"}


def _public_titles(client) -> list[str]:
    body = json.loads(client.get("/api/announcements").data)
    return [a["title"] for a in body["announcements"]]


def test_public_list_reachable_by_anonymous(flask_client):
    resp = flask_client.get("/api/announcements")
    assert resp.status_code == 200
    assert json.loads(resp.data)["announcements"] == []


def test_owner_can_send_and_it_appears_publicly(signed_in_client, flask_client):
    client, _ = signed_in_client(hf_user_id="o-1", login="owner", role="owner")
    resp = client.post(
        "/api/admin/announcements",
        json={"title": "Welcome", "body": "Thanks for testing"},
        headers=_ORIGIN,
    )
    assert resp.status_code == 201
    created = json.loads(resp.data)
    assert created["title"] == "Welcome"
    assert created["author_login"] == "owner"
    assert created["revoked_at"] is None

    # Visible to an anonymous visitor.
    assert _public_titles(flask_client) == ["Welcome"]


def test_empty_title_is_rejected(signed_in_client):
    client, _ = signed_in_client(hf_user_id="o-2", login="owner", role="owner")
    resp = client.post("/api/admin/announcements", json={"title": "  "}, headers=_ORIGIN)
    assert resp.status_code == 400


def test_maintainer_cannot_send(signed_in_client):
    client, _ = signed_in_client(hf_user_id="m-1", login="mant", role="maintainer")
    resp = client.post("/api/admin/announcements", json={"title": "x"}, headers=_ORIGIN)
    assert resp.status_code == 403


def test_contributor_cannot_send(signed_in_client):
    client, _ = signed_in_client(hf_user_id="c-1", login="contrib", role="contributor")
    resp = client.post("/api/admin/announcements", json={"title": "x"}, headers=_ORIGIN)
    assert resp.status_code == 403


def test_anonymous_cannot_send(flask_client):
    resp = flask_client.post("/api/admin/announcements", json={"title": "x"}, headers=_ORIGIN)
    assert resp.status_code == 401


def test_maintainer_cannot_list_admin(signed_in_client):
    client, _ = signed_in_client(hf_user_id="m-2", login="mant", role="maintainer")
    assert client.get("/api/admin/announcements").status_code == 403


def test_revoke_removes_from_public_list(signed_in_client, flask_client):
    client, _ = signed_in_client(hf_user_id="o-3", login="owner", role="owner")
    created = json.loads(
        client.post("/api/admin/announcements", json={"title": "Temp"}, headers=_ORIGIN).data
    )
    aid = created["id"]
    assert _public_titles(flask_client) == ["Temp"]

    assert client.post(f"/api/admin/announcements/{aid}/revoke", headers=_ORIGIN).status_code == 204
    assert _public_titles(flask_client) == []

    # Still present in the admin management list, marked revoked.
    admin_rows = json.loads(client.get("/api/admin/announcements").data)["announcements"]
    revoked = next(r for r in admin_rows if r["id"] == aid)
    assert revoked["revoked_at"] is not None


def test_revoke_unknown_is_404(signed_in_client):
    client, _ = signed_in_client(hf_user_id="o-4", login="owner", role="owner")
    assert client.post("/api/admin/announcements/9999/revoke", headers=_ORIGIN).status_code == 404
