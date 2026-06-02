"""Dev-only routes — functionally available only when ``INSPECTOR_DEV_MODE=1``.

``POST /api/dev/role`` flips the unsigned ``inspector_dev_role`` cookie so
the synthetic dev user (see ``services/auth.py``) presents as the chosen
role on the next request. The route is registered unconditionally (Flask
disallows post-boot blueprint registration, which would break tests that
flip dev mode per-test) but ``abort(404)`` is the very first thing the
handler does when dev mode is off. Net surface area on the HF Space deploy:
one route that always 404s, with no side effects.

The ``/api/dev/guide-flag(s)`` routes are the maintainer's accordion-guide
example flagging tool (see ``services/segments/guide_flags.py`` and
``docs/reference/accordion-guides.md``): flag an edit from the History panel,
queue it to a local JSONL, and the offline builder turns it into a guide
example. Same dev-only gate — they 404 on the deployed Space.
"""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, make_response, request

from services import auth as auth_service
from services.segments import guide_flags
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


# --- Accordion-guide example flagging (dev-only authoring tool) -------------


@dev_bp.route("/guide-flags", methods=["GET"])
def dev_list_guide_flags():
    if not auth_service.is_dev_mode():
        abort(404)
    return jsonify({"flags": guide_flags.load_flags()})


@dev_bp.route("/guide-flag", methods=["POST"])
@require_same_origin
def dev_add_guide_flag():
    if not auth_service.is_dev_mode():
        abort(404)

    body = request.get_json(silent=True) or {}
    if not body.get("flagged_by"):
        user = auth_service.current_user()
        if user is not None:
            body["flagged_by"] = getattr(user, "login", None) or getattr(user, "role", None)

    try:
        record = guide_flags.append_flag(body)
    except guide_flags.GuideFlagError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "flag": record})


@dev_bp.route("/guide-flag/<flag_id>", methods=["DELETE"])
@require_same_origin
def dev_delete_guide_flag(flag_id):
    if not auth_service.is_dev_mode():
        abort(404)
    return jsonify({"ok": guide_flags.delete_flag(flag_id)})
