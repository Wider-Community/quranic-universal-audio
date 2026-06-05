"""Admin Permissions-tab endpoints (owner-only).

- ``GET  /api/admin/permissions``               → grouped capability matrix
  (registry ⊕ overrides) for the Permissions compartment.
- ``POST /api/admin/permissions/<cap>/<tier>``  → toggle one cell. Body is
  ``{"allowed": true|false}`` or ``{"reset": true}`` (back to default).
  Instant + audited (``access.permission_changed``).

Both routes are gated by the owner-only-fixed ``manage_permissions``
capability — the recovery anchor, so only owners can see or change the matrix.
The mutating route stacks ``@require_same_origin`` for CSRF defense.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from routes._admin_helpers import actor_for
from services.admin import permissions as permissions_service
from utils.decorators import require_capability, require_same_origin

admin_permissions_bp = Blueprint("admin_permissions", __name__, url_prefix="/api/admin")


@admin_permissions_bp.route("/permissions", methods=["GET"])
@require_capability("manage_permissions")
def get_permissions(user):
    resp = jsonify(permissions_service.build_matrix().model_dump(mode="json"))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@admin_permissions_bp.route("/permissions/<capability>/<tier>", methods=["POST"])
@require_same_origin
@require_capability("manage_permissions")
def set_permission(user, capability: str, tier: str):
    body = request.get_json(silent=True) or {}
    actor = actor_for(user)
    try:
        if body.get("reset"):
            value = permissions_service.reset_grant(
                capability_id=capability,
                tier=tier,
                actor=actor,
            )
        else:
            allowed = body.get("allowed")
            if not isinstance(allowed, bool):
                return jsonify(
                    {
                        "error": "body must include boolean 'allowed' (or 'reset': true)",
                    }
                ), 400
            value = permissions_service.set_grant(
                capability_id=capability,
                tier=tier,
                allowed=allowed,
                actor=actor,
            )
    except permissions_service.PermissionChangeError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(
        {
            "ok": True,
            "capability": capability,
            "tier": tier,
            "allowed": value,
        }
    )
