"""Admin Users routes: role gate (401/403/200) + detail 404 + visitor-stats."""

from __future__ import annotations


def test_users_anonymous_401(flask_client):
    assert flask_client.get("/api/admin/users").status_code == 401


def test_users_contributor_403(signed_in_client):
    client, _ = signed_in_client(role="contributor")
    assert client.get("/api/admin/users").status_code == 403


def test_users_maintainer_200(signed_in_client):
    client, _ = signed_in_client(hf_user_id="m", login="m", role="maintainer")
    resp = client.get("/api/admin/users")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "users" in body and "summary" in body
    ids = {u["hf_user_id"] for u in body["users"]}
    assert "m" in ids


def test_users_owner_200(signed_in_client):
    client, _ = signed_in_client(role="owner")
    assert client.get("/api/admin/users").status_code == 200


def test_detail_unknown_404(signed_in_client):
    client, _ = signed_in_client(role="maintainer")
    assert client.get("/api/admin/users/ghost").status_code == 404


def test_detail_known_200(signed_in_client):
    client, user = signed_in_client(hf_user_id="known", login="known", role="maintainer")
    resp = client.get(f"/api/admin/users/{user['hf_user_id']}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["hf_user_id"] == "known"
    assert "stats" in body and "claims_history" in body


def test_visitor_stats_gate_and_shape(flask_client, signed_in_client):
    assert flask_client.get("/api/admin/visitor-stats").status_code == 401
    client, _ = signed_in_client(role="maintainer")
    resp = client.get("/api/admin/visitor-stats")
    assert resp.status_code == 200
    assert "today" in resp.get_json()
