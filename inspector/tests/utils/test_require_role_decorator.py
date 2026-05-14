"""Tests for ``utils.decorators.require_role`` — the reusable role gate for
admin routes.

The decorator composes ``require_signed_in_or_401`` + ``require_role_or_403``
and injects the authenticated user as the first positional argument into
the wrapped handler. It's the single drift-resistant primitive for new
admin endpoints; existing routes can migrate later.
"""

from __future__ import annotations

import json


def _register_test_blueprint():
    """Attach a fresh test blueprint to the module-level Flask app with
    routes wrapped in the decorator under test. Idempotent across runs in
    the same test session.
    """
    from flask import Blueprint, jsonify

    from scripts.lib.schemas import Role

    from app import app
    from utils.decorators import require_role

    if "test_require_role" in app.blueprints:
        return

    bp = Blueprint("test_require_role", __name__, url_prefix="/api/_test_role")

    @bp.route("/maintainer-only", methods=["POST"])
    @require_role(Role.MAINTAINER, Role.OWNER)
    def maintainer_only(user):
        return jsonify({
            "ok": True,
            "hf_user_id": user.hf_user_id,
            "role": str(user.role),
        })

    @bp.route("/owner-only", methods=["POST"])
    @require_role(Role.OWNER)
    def owner_only(user):
        return jsonify({"ok": True, "role": str(user.role)})

    @bp.route("/with-arg/<slug>", methods=["POST"])
    @require_role(Role.MAINTAINER, Role.OWNER)
    def with_arg(user, slug):
        return jsonify({"slug": slug, "hf_user_id": user.hf_user_id})

    app.register_blueprint(bp)


_HEADERS = {"Origin": "http://localhost"}


def test_anonymous_request_returns_401(signed_in_client):
    """No identity cookie → 401."""
    _register_test_blueprint()
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
    _register_test_blueprint()
    client, _ = signed_in_client(role="contributor")
    res = client.post(
        "/api/_test_role/maintainer-only",
        headers=_HEADERS,
        data="{}",
        content_type="application/json",
    )
    assert res.status_code == 403


def test_maintainer_passes_maintainer_gate(signed_in_client):
    _register_test_blueprint()
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
    _register_test_blueprint()
    client, _ = signed_in_client(role="owner", hf_user_id="u-O", login="owner1")
    res = client.post(
        "/api/_test_role/maintainer-only",
        headers=_HEADERS,
        data="{}",
        content_type="application/json",
    )
    assert res.status_code == 200


def test_owner_only_gate_rejects_maintainer(signed_in_client):
    _register_test_blueprint()
    client, _ = signed_in_client(role="maintainer", hf_user_id="u-M")
    res = client.post(
        "/api/_test_role/owner-only",
        headers=_HEADERS,
        data="{}",
        content_type="application/json",
    )
    assert res.status_code == 403


def test_owner_only_gate_admits_owner(signed_in_client):
    _register_test_blueprint()
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
    _register_test_blueprint()
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
