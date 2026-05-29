"""Route tests for the owner-only Permissions endpoints + end-to-end
enforcement (toggling a capability flips a maintainer's access live).
"""

from __future__ import annotations

import json

_ORIGIN = {"Origin": "http://localhost"}


# ---- GET /api/admin/permissions (owner-only) ----


def test_get_matrix_owner_ok(signed_in_client):
    client, _ = signed_in_client(hf_user_id="o-1", login="owner", role="owner")
    resp = client.get("/api/admin/permissions")
    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body["tiers"] == ["anonymous", "contributor", "maintainer"]
    assert len(body["groups"]) >= 1
    # manage_permissions row is present + flagged fixed.
    rows = [c for g in body["groups"] for c in g["capabilities"]]
    mp = next(c for c in rows if c["id"] == "manage_permissions")
    assert mp["owner_only_fixed"] is True


def test_get_matrix_maintainer_forbidden(signed_in_client):
    client, _ = signed_in_client(hf_user_id="m-1", login="maint", role="maintainer")
    assert client.get("/api/admin/permissions").status_code == 403


def test_get_matrix_anonymous_unauthorized(flask_client):
    assert flask_client.get("/api/admin/permissions").status_code == 401


# ---- POST toggle ----


def test_toggle_persists_and_shows_in_matrix(signed_in_client):
    client, _ = signed_in_client(hf_user_id="o-1", login="owner", role="owner")
    resp = client.post(
        "/api/admin/permissions/claim.force_release/maintainer",
        json={"allowed": True},
        headers=_ORIGIN,
    )
    assert resp.status_code == 200
    assert json.loads(resp.data)["allowed"] is True

    matrix = json.loads(client.get("/api/admin/permissions").data)
    rows = [c for g in matrix["groups"] for c in g["capabilities"]]
    fr = next(c for c in rows if c["id"] == "claim.force_release")
    assert fr["maintainer"]["allowed"] is True
    assert fr["maintainer"]["is_default"] is False


def test_toggle_manage_permissions_rejected(signed_in_client):
    client, _ = signed_in_client(hf_user_id="o-1", login="owner", role="owner")
    resp = client.post(
        "/api/admin/permissions/manage_permissions/maintainer",
        json={"allowed": True},
        headers=_ORIGIN,
    )
    assert resp.status_code == 400


def test_toggle_anonymous_on_action_cap_rejected(signed_in_client):
    client, _ = signed_in_client(hf_user_id="o-1", login="owner", role="owner")
    resp = client.post(
        "/api/admin/permissions/claim.acquire/anonymous",
        json={"allowed": True},
        headers=_ORIGIN,
    )
    assert resp.status_code == 400


def test_toggle_by_maintainer_forbidden(signed_in_client):
    client, _ = signed_in_client(hf_user_id="m-1", login="maint", role="maintainer")
    resp = client.post(
        "/api/admin/permissions/reciter.publish/contributor",
        json={"allowed": True},
        headers=_ORIGIN,
    )
    assert resp.status_code == 403


def test_reset_returns_to_default(signed_in_client):
    client, _ = signed_in_client(hf_user_id="o-1", login="owner", role="owner")
    client.post(
        "/api/admin/permissions/reciter.publish/contributor",
        json={"allowed": True},
        headers=_ORIGIN,
    )
    resp = client.post(
        "/api/admin/permissions/reciter.publish/contributor",
        json={"reset": True},
        headers=_ORIGIN,
    )
    assert resp.status_code == 200
    assert json.loads(resp.data)["allowed"] is False  # back to default


# ---- End-to-end enforcement: toggle flips a maintainer's access live ----


def test_toggle_flips_maintainer_force_release_live(signed_in_client):
    owner, _ = signed_in_client(hf_user_id="o-1", login="owner", role="owner")
    maint, _ = signed_in_client(hf_user_id="m-1", login="maint", role="maintainer")

    # Default: maintainer cannot force-release (owner-only capability).
    before = maint.post("/api/admin/claim/force-release/some_slug", headers=_ORIGIN)
    assert before.status_code == 403

    # Owner grants claim.force_release to the maintainer tier.
    assert owner.post(
        "/api/admin/permissions/claim.force_release/maintainer",
        json={"allowed": True},
        headers=_ORIGIN,
    ).status_code == 200

    # Now the maintainer passes the capability gate (404 = unknown slug, NOT
    # 403 = forbidden — the gate let them through).
    after = maint.post("/api/admin/claim/force-release/some_slug", headers=_ORIGIN)
    assert after.status_code != 403


def test_toggle_emits_audit(signed_in_client):
    client, _ = signed_in_client(hf_user_id="o-1", login="owner", role="owner")
    client.post(
        "/api/admin/permissions/reciter.publish/contributor",
        json={"allowed": True},
        headers=_ORIGIN,
    )
    from services.db import connection

    events = [
        r[0]
        for r in connection.get_conn().execute("SELECT event FROM transitions").fetchall()
    ]
    assert "access.permission_changed" in events
