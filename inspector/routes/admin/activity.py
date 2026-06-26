"""Owner-only public-feed tombstone endpoint.

The admin notifications rail was retired (admin awareness now lives in the
Admin dashboard — Users / Requests / Reviews tabs); only the public-feed
owner-delete affordance remains as a moderation surface, exposed under the
``/api/public/activity`` namespace.

``DELETE /api/public/activity/<audit_id>`` writes a row into
``activity_tombstones`` so the public feed filters the referenced audit
record out for everyone. Reason ≥10 chars required; ``@require_same_origin``
stacks on top of ``@require_role(OWNER)``.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from routes._admin_helpers import actor_for, validate_reason
from services import activity_state as activity_state_service
from utils.decorators import require_capability, require_same_origin

public_activity_admin_bp = Blueprint(
    "public_activity_admin",
    __name__,
    url_prefix="/api/public/activity",
)


@public_activity_admin_bp.route("/<audit_id>", methods=["DELETE"])
@require_same_origin
@require_capability("activity.delete")
def delete_public(user, audit_id: str):
    """Owner-only: tombstone a public-feed card. Reason ≥10 chars required."""
    body = request.get_json(silent=True) or {}
    reason, err = validate_reason(body)
    if err is not None:
        return err
    # required=True guarantees a non-empty reason whenever err is None.
    assert reason is not None
    activity_state_service.delete(audit_id, actor=actor_for(user), reason=reason)
    return jsonify({"ok": True, "audit_id": audit_id})
