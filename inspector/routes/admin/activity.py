"""Admin/owner activity-rail endpoints.

Three surfaces:

- ``GET  /api/admin/activity?archived=&cursor=&limit=`` — admin-only feed
  for maintainers + owners. Owners see the actor's HF login on each card;
  maintainers see identity-redacted cards.
- ``POST /api/admin/activity/dismiss`` — per-user dismiss (maintainer+).
- ``POST /api/admin/activity/undismiss`` — per-user undismiss (maintainer+).
- ``DELETE /api/public/activity/<audit_id>`` — owner-only global tombstone
  on a public-rail card. Reason ≥10 chars required.

All POST/DELETE handlers stack ``@require_same_origin`` for CSRF defense
on top of ``@require_role`` for the tier check.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from scripts.lib.schemas import Role

from routes._admin_helpers import actor_for, validate_reason

from services import activity_state as activity_state_service
from services import admin_activity as admin_activity_service
from services import permissions

from utils.decorators import require_role, require_same_origin


admin_activity_bp = Blueprint(
    "admin_activity", __name__, url_prefix="/api/admin/activity",
)
public_activity_admin_bp = Blueprint(
    "public_activity_admin", __name__, url_prefix="/api/public/activity",
)


def _parse_int(raw: str | None, default: int) -> tuple[int, str | None]:
    if raw is None or raw == "":
        return default, None
    try:
        return int(raw), None
    except ValueError:
        return default, f"{raw!r} is not an integer"


@admin_activity_bp.route("", methods=["GET"])
@require_role(Role.MAINTAINER, Role.OWNER)
def feed(user):
    cursor, err = _parse_int(request.args.get("cursor"), 0)
    if err is not None:
        return jsonify({"error": f"cursor must be an integer ({err})"}), 400
    if cursor < 0:
        return jsonify({"error": "cursor must be >= 0"}), 400
    limit, err = _parse_int(request.args.get("limit"), 50)
    if err is not None:
        return jsonify({"error": f"limit must be an integer ({err})"}), 400
    if limit < 1 or limit > 500:
        return jsonify({"error": "limit must be between 1 and 500"}), 400
    archived = (request.args.get("archived") or "").lower() in ("1", "true", "yes")

    payload = admin_activity_service.feed(
        caller_role=permissions.role_of(user),
        caller_hf_id=user.hf_user_id,
        cursor=cursor,
        limit=limit,
        archived=archived,
    )
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@admin_activity_bp.route("/dismiss", methods=["POST"])
@require_same_origin
@require_role(Role.MAINTAINER, Role.OWNER)
def dismiss(user):
    body = request.get_json(silent=True) or {}
    audit_id = (body.get("audit_id") or "").strip()
    if not audit_id:
        return jsonify({"error": "audit_id is required"}), 400
    activity_state_service.dismiss(audit_id, actor=actor_for(user))
    return jsonify({"ok": True, "audit_id": audit_id})


@admin_activity_bp.route("/undismiss", methods=["POST"])
@require_same_origin
@require_role(Role.MAINTAINER, Role.OWNER)
def undismiss(user):
    body = request.get_json(silent=True) or {}
    audit_id = (body.get("audit_id") or "").strip()
    if not audit_id:
        return jsonify({"error": "audit_id is required"}), 400
    activity_state_service.undismiss(audit_id, actor=actor_for(user))
    return jsonify({"ok": True, "audit_id": audit_id})


@public_activity_admin_bp.route("/<audit_id>", methods=["DELETE"])
@require_same_origin
@require_role(Role.OWNER)
def delete_public(user, audit_id: str):
    """Owner-only: tombstone a public-feed card. Reason ≥10 chars required."""
    body = request.get_json(silent=True) or {}
    reason, err = validate_reason(body)
    if err is not None:
        return err
    activity_state_service.delete(audit_id, actor=actor_for(user), reason=reason)
    return jsonify({"ok": True, "audit_id": audit_id})
