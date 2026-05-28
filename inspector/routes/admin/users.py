"""Admin Users-panel endpoints (maintainer/owner only).

- ``GET  /api/admin/users``             master list (cached on db_seq).
- ``GET  /api/admin/users/<hf_user_id>`` per-user detail (lazy, uncached).
- ``GET  /api/admin/visitor-stats``      site traffic rollup (added with the
                                        visitor-analytics phase).
- ``POST /api/admin/users/<hf_user_id>/role`` owner-only role change (picker).

GETs are read-only (no ``@require_same_origin``); the role POST is mutating and
owner-only, so it carries both ``@require_same_origin`` and
``@require_role(Role.OWNER)``.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from scripts.lib.schemas import Role

from routes._admin_helpers import actor_for as _actor_for

from services.admin import users as users_service
from services.admin import visitors as visitor_service
from services.auth import access as access_service

from utils.decorators import require_role, require_same_origin

admin_users_bp = Blueprint("admin_users", __name__, url_prefix="/api/admin")

# Roles assignable through the picker (``pipeline`` is internal-only).
_ASSIGNABLE_ROLES = {Role.CONTRIBUTOR, Role.MAINTAINER, Role.OWNER}


@admin_users_bp.route("/users")
@require_role(Role.MAINTAINER, Role.OWNER)
def list_users(user):
    return jsonify(users_service.list_users())


@admin_users_bp.route("/users/<hf_user_id>")
@require_role(Role.MAINTAINER, Role.OWNER)
def user_detail(user, hf_user_id):
    detail = users_service.get_user_detail(hf_user_id)
    if detail is None:
        return jsonify({"error": "unknown user"}), 404
    return jsonify(detail)


@admin_users_bp.route("/visitor-stats")
@require_role(Role.MAINTAINER, Role.OWNER)
def visitor_stats(user):
    return jsonify(visitor_service.get_visitor_stats())


@admin_users_bp.route("/users/<hf_user_id>/role", methods=["POST"])
@require_same_origin
@require_role(Role.OWNER)
def set_user_role(user, hf_user_id):
    """Owner-only: change a user's role (contributor / maintainer / owner)."""
    body = request.get_json(silent=True) or {}
    role_raw = (body.get("role") or "").strip()
    try:
        target = Role(role_raw)
    except ValueError:
        return jsonify({"error": f"unknown role {role_raw!r}"}), 400
    if target not in _ASSIGNABLE_ROLES:
        return jsonify({"error": f"role {target.value!r} is not assignable"}), 400

    login = (body.get("login") or "").strip() or None
    try:
        result = users_service.set_role(
            hf_user_id=hf_user_id,
            target_role=target,
            actor=_actor_for(user),
            login=login,
        )
    except users_service.LastOwnerError as e:
        return jsonify({"error": str(e)}), 409
    except access_service.NotAuthorized as e:
        return jsonify({"error": str(e)}), 403
    except access_service.MemberNotFound:
        return jsonify({"error": f"member {hf_user_id} not found"}), 404
    except access_service.AccessError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result)
