"""Tests for ``utils.decorators.require_role`` — the reusable role gate for
admin routes.

The decorator composes ``require_signed_in_or_401`` + ``require_role_or_403``
and injects the authenticated user as the first positional argument into
the wrapped handler. It's the single drift-resistant primitive for new
admin endpoints; existing routes can migrate later.
"""

from __future__ import annotations

import json


def _register_test_routes():
    """Attach test routes for the decorator at module import time.

    Routes must be registered before the Flask app handles its first
    request, which is why this runs at module load rather than inside a
    fixture. Idempotent across pytest collection passes.
    """
    from flask import jsonify

    from qua_shared.schemas import Role

    from app import app
    from utils.decorators import require_role

    if app.view_functions.get("_test_role_maintainer_only") is not None:
        return

    @require_role(Role.MAINTAINER, Role.OWNER)
    def maintainer_only(user):
        return jsonify({
            "ok": True,
            "hf_user_id": user.hf_user_id,
            "role": str(user.role),
        })

    @require_role(Role.OWNER)
    def owner_only(user):
        return jsonify({"ok": True, "role": str(user.role)})

    @require_role(Role.MAINTAINER, Role.OWNER)
    def with_arg(user, slug):
        return jsonify({"slug": slug, "hf_user_id": user.hf_user_id})

    app.add_url_rule(
        "/api/_test_role/maintainer-only",
        endpoint="_test_role_maintainer_only",
        view_func=maintainer_only,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/_test_role/owner-only",
        endpoint="_test_role_owner_only",
        view_func=owner_only,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/_test_role/with-arg/<slug>",
        endpoint="_test_role_with_arg",
        view_func=with_arg,
        methods=["POST"],
    )


_register_test_routes()


_HEADERS = {"Origin": "http://localhost"}


def test_anonymous_request_returns_401(signed_in_client):
    """No identity cookie → 401."""
    from app import app

    client = app.test_client()
    res = client.post(
        "/api/_test_role/maintainer-only",
        headers=_HEADERS,
        data="{}",
        content_type="application/json",
    )
    assert res.status_code == 401


def test_contributor_returns_403(signed_in_client):
    client, _ = signed_in_client(role="contributor")
    res = client.post(
        "/api/_test_role/maintainer-only",
        headers=_HEADERS,
        data="{}",
        content_type="application/json",
    )
    assert res.status_code == 403


def test_maintainer_passes_maintainer_gate(signed_in_client):
    client, user = signed_in_client(role="maintainer", hf_user_id="u-M", login="mod")
    res = client.post(
        "/api/_test_role/maintainer-only",
        headers=_HEADERS,
        data="{}",
        content_type="application/json",
    )
    assert res.status_code == 200
    body = json.loads(res.data)
    assert body["ok"] is True
    assert body["hf_user_id"] == "u-M"
    assert body["role"] == "maintainer"


def test_owner_passes_maintainer_gate(signed_in_client):
    """Owner satisfies any gate that admits maintainers."""
    client, _ = signed_in_client(role="owner", hf_user_id="u-O", login="owner1")
    res = client.post(
        "/api/_test_role/maintainer-only",
        headers=_HEADERS,
        data="{}",
        content_type="application/json",
    )
    assert res.status_code == 200


def test_owner_only_gate_rejects_maintainer(signed_in_client):
    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M")
    res = client.post(
        "/api/_test_role/owner-only",
        headers=_HEADERS,
        data="{}",
        content_type="application/json",
    )
    assert res.status_code == 403


def test_owner_only_gate_admits_owner(signed_in_client):
    client, _ = signed_in_client(role="owner", hf_user_id="u-O")
    res = client.post(
        "/api/_test_role/owner-only",
        headers=_HEADERS,
        data="{}",
        content_type="application/json",
    )
    assert res.status_code == 200


def test_route_path_args_still_pass_through(signed_in_client):
    """Decorator injects ``user`` first but preserves remaining route args."""
    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M")
    res = client.post(
        "/api/_test_role/with-arg/some-slug",
        headers=_HEADERS,
        data="{}",
        content_type="application/json",
    )
    assert res.status_code == 200
    body = json.loads(res.data)
    assert body["slug"] == "some-slug"
    assert body["hf_user_id"] == "u-M"
