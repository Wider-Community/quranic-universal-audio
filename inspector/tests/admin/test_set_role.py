"""Owner-only role picker: POST /api/admin/users/<id>/role + the
``access.revoke(cascade_release=...)`` decoupling that backs demote-preserves-claim.

Gate matrix: owner-only (403 for maintainer), same-origin (403 without Origin),
input validation (400), the last-owner guard (409), and the three dispatch paths
(grant / update / demote). The core behavioural assertion is that demoting a
maintainer who holds an open claim leaves that claim open — a contributor is a
valid claim holder, so demote is not offboarding.
"""

from __future__ import annotations

ORIGIN = {"Origin": "http://localhost"}


def _role(hf_user_id: str):
    from services.db import repo_access

    return repo_access.resolve_role(hf_user_id)


# ---- dispatch paths ----------------------------------------------------------


def test_grant_contributor_to_maintainer(signed_in_client, seed_role):
    client, _ = signed_in_client(hf_user_id="o", login="o", role="owner")
    seed_role("c", login="c", role="contributor")  # just ensures the users row

    resp = client.post("/api/admin/users/c/role", json={"role": "maintainer"}, headers=ORIGIN)
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["member"]["role"] == "maintainer"
    assert _role("c") == "maintainer"


def test_update_maintainer_owner_round_trip(signed_in_client, seed_role):
    client, _ = signed_in_client(hf_user_id="o", login="o", role="owner")
    seed_role("m", login="m", role="maintainer")

    up = client.post("/api/admin/users/m/role", json={"role": "owner"}, headers=ORIGIN)
    assert up.status_code == 200, up.get_json()
    assert up.get_json()["member"]["role"] == "owner"

    # Two owners now (o + m), so demoting m back is allowed.
    down = client.post("/api/admin/users/m/role", json={"role": "maintainer"}, headers=ORIGIN)
    assert down.status_code == 200, down.get_json()
    assert down.get_json()["member"]["role"] == "maintainer"


def test_demote_preserves_open_claim(signed_in_client, seed_role, seed_state):
    from qua_shared.schemas import Role
    from services.db import repo_claims

    client, _ = signed_in_client(hf_user_id="o", login="o", role="owner")
    seed_role("m", login="m", role="maintainer")
    seed_state("recd", state="under_review", assignee_hf_id="m", assignee_login="m")

    resp = client.post("/api/admin/users/m/role", json={"role": "contributor"}, headers=ORIGIN)
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json() == {"ok": True, "role": "contributor"}

    assert _role("m") == Role.CONTRIBUTOR
    # The claim survives the demotion — a contributor is a valid holder.
    assert repo_claims.open_claims_for_user("m") == ["recd"]


def test_noop_same_role(signed_in_client, seed_role):
    client, _ = signed_in_client(hf_user_id="o", login="o", role="owner")
    seed_role("m", login="m", role="maintainer")

    resp = client.post("/api/admin/users/m/role", json={"role": "maintainer"}, headers=ORIGIN)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("noop") is True and body["role"] == "maintainer"


# ---- last-owner guard --------------------------------------------------------


def test_last_owner_self_demote_409(signed_in_client):
    from qua_shared.schemas import Role

    client, _ = signed_in_client(hf_user_id="o", login="o", role="owner")

    resp = client.post("/api/admin/users/o/role", json={"role": "contributor"}, headers=ORIGIN)
    assert resp.status_code == 409, resp.get_json()
    assert resp.get_json()["code"] == "LAST_OWNER"
    assert _role("o") == "owner"  # unchanged


def test_demote_owner_with_two_owners_ok(signed_in_client, seed_role):
    client, _ = signed_in_client(hf_user_id="o", login="o", role="owner")
    seed_role("o2", login="o2", role="owner")

    resp = client.post("/api/admin/users/o2/role", json={"role": "maintainer"}, headers=ORIGIN)
    assert resp.status_code == 200, resp.get_json()
    assert _role("o2") == "maintainer"
    assert _role("o") == "owner"


# ---- gate / validation -------------------------------------------------------


def test_maintainer_actor_403(signed_in_client, seed_role):
    client, _ = signed_in_client(hf_user_id="m", login="m", role="maintainer")
    seed_role("c", login="c", role="contributor")

    resp = client.post("/api/admin/users/c/role", json={"role": "owner"}, headers=ORIGIN)
    assert resp.status_code == 403


def test_unknown_role_400(signed_in_client):
    client, _ = signed_in_client(hf_user_id="o", login="o", role="owner")
    resp = client.post("/api/admin/users/o/role", json={"role": "wizard"}, headers=ORIGIN)
    assert resp.status_code == 400


def test_pipeline_role_not_assignable_400(signed_in_client):
    client, _ = signed_in_client(hf_user_id="o", login="o", role="owner")
    resp = client.post("/api/admin/users/o/role", json={"role": "pipeline"}, headers=ORIGIN)
    assert resp.status_code == 400


def test_missing_same_origin_403(signed_in_client, seed_role):
    client, _ = signed_in_client(hf_user_id="o", login="o", role="owner")
    seed_role("m", login="m", role="maintainer")
    # No Origin / Referer header → require_same_origin rejects before role logic.
    resp = client.post("/api/admin/users/m/role", json={"role": "owner"})
    assert resp.status_code == 403


# ---- service-level cascade flag ----------------------------------------------


def _owner_actor():
    from qua_shared.schemas import Actor, Role

    return Actor(hf_user_id="o", login_at_time="o", role=Role.OWNER.value)


def test_revoke_cascade_release_false_keeps_claim(seed_role, seed_state):
    from services.auth import access
    from services.db import repo_claims

    seed_role("m", login="m", role="maintainer")
    seed_state("recc", state="under_review", assignee_hf_id="m", assignee_login="m")

    _member, released = access.revoke(hf_user_id="m", actor=_owner_actor(), cascade_release=False)
    assert released == []
    assert repo_claims.open_claims_for_user("m") == ["recc"]


def test_revoke_default_releases_claim(seed_role, seed_state):
    from services.auth import access
    from services.db import repo_claims

    seed_role("m", login="m", role="maintainer")
    seed_state("recc", state="under_review", assignee_hf_id="m", assignee_login="m")

    _member, released = access.revoke(hf_user_id="m", actor=_owner_actor())
    assert released == ["recc"]
    assert repo_claims.open_claims_for_user("m") == []
