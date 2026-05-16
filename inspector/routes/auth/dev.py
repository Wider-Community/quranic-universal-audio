"""Dev-only routes — functionally available only when ``INSPECTOR_DEV_MODE=1``.

``POST /api/dev/role`` flips the unsigned ``inspector_dev_role`` cookie so
the synthetic dev user (see ``services/auth.py``) presents as the chosen
role on the next request. The route is registered unconditionally (Flask
disallows post-boot blueprint registration, which would break tests that
flip dev mode per-test) but ``abort(404)`` is the very first thing the
handler does when dev mode is off. Net surface area on the HF Space deploy:
one route that always 404s, with no side effects.
"""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, make_response, request

from services import auth as auth_service
from utils.decorators import require_same_origin

dev_bp = Blueprint("dev", __name__, url_prefix="/api/dev")


@dev_bp.route("/role", methods=["POST"])
@require_same_origin
def dev_set_role():
    if not auth_service.is_dev_mode():
        abort(404)

    body = request.get_json(silent=True) or {}
    role = body.get("role")
    if role not in auth_service.DEV_ROLE_VALUES:
        return jsonify({
            "error": "invalid role",
            "allowed": list(auth_service.DEV_ROLE_VALUES),
        }), 400

    resp = make_response(jsonify({"ok": True, "role": role}))
    resp.set_cookie(
        auth_service.DEV_ROLE_COOKIE_NAME,
        role,
        max_age=60 * 60 * 24 * 30,  # 30 days
        httponly=True,
        samesite="Lax",
        secure=False,
        path="/",
    )
    return resp
