"""Request-flow endpoints — user submit + admin review/reject + undiscard.

User-facing:
- ``POST /api/reciter/<slug>/request`` — any signed-in user can submit a
  request with proposed catalog edits + free-form comments. Transitions
  the row CATALOGUED → AWAITING_ALIGNMENT and persists the pending entry.

Admin (maintainer + owner):
- ``GET  /api/admin/request/<slug>`` — fetch the pending request payload.
  Requester actor identity is included for owners, redacted for maintainers
  (mirrors the admin-activity-rail redaction pattern).
- ``POST /api/admin/request/<slug>/reject-soft`` — send back; row returns
  to CATALOGUED. Reason ≥10 chars required.
- ``POST /api/admin/request/<slug>/reject-hard`` — discard; row goes back
  to CATALOGUED + visibility=DISCARDED. Reason ≥10 chars required.

Owner-only:
- ``POST /api/admin/reciter/<slug>/undiscard`` — restore a discarded
  row to visibility=PUBLIC. Reason ≥10 chars required. Wraps the
  existing ``reciter.undiscarded`` state event (which today requires
  maintainer); the route adds the owner-only gate.

All POST routes stack ``@require_same_origin`` for CSRF defense on top
of ``@require_role`` for the tier check.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from scripts.lib.schemas import Role

from routes._admin_helpers import actor_for, validate_reason

from services import pending_requests as pending_requests_service
from services import permissions
from services import state as state_service

from utils.decorators import require_role, require_same_origin


requests_bp = Blueprint("requests", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# User: submit
# ---------------------------------------------------------------------------


@requests_bp.route("/reciter/<slug>/request", methods=["POST"])
@require_same_origin
@require_role(Role.CONTRIBUTOR, Role.MAINTAINER, Role.OWNER)
def submit_request(user, slug: str):
    body = request.get_json(silent=True) or {}

    proposed_edits = body.get("proposed_edits")
    if proposed_edits is None:
        proposed_edits = {}
    elif not isinstance(proposed_edits, dict):
        return jsonify({"error": "proposed_edits must be an object"}), 400

    comments = body.get("comments")
    if comments is not None and not isinstance(comments, str):
        return jsonify({"error": "comments must be a string or null"}), 400

    # Verify the slug refers to a real catalog delivery — the state-machine
    # handler accepts `before is None` (no state row yet) so it cannot tell a
    # never-seen slug apart from a not-yet-progressed one. Route-layer check
    # keeps random slugs out of the state file.
    from services import catalog as catalog_service
    if catalog_service.find_delivery(slug) is None:
        return jsonify({"error": "unknown reciter"}), 404

    # Reject up front (HTTP 409) when a pending entry exists, so the
    # frontend can surface a clean "already pending" message instead of a
    # 400 from the state-machine handler.
    if pending_requests_service.get(slug) is not None:
        return jsonify({"error": "request already pending for this reciter"}), 409

    try:
        new_row = state_service.transition(
            slug,
            "reciter.requested",
            actor=actor_for(user),
            payload={
                "proposed_edits": proposed_edits,
                "comments": comments,
            },
        )
    except state_service.UnknownReciter:
        return jsonify({"error": "unknown reciter"}), 404
    except state_service.NotAuthorizedForTransition as e:
        return jsonify({"error": str(e)}), 403
    except state_service.InvalidTransition as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"ok": True, "slug": slug, "state": new_row.state.value})


# ---------------------------------------------------------------------------
# Admin: fetch pending
# ---------------------------------------------------------------------------


def _pending_to_payload(pending, *, owner: bool) -> dict:
    """Serialize a ``PendingRequest`` for the admin review form.

    Owners see the full requester actor identity; maintainers see only the
    role. Mirrors ``services.admin_activity._to_card`` tier-aware shape.
    """
    payload = {
        "slug": pending.slug,
        "submitted_at": pending.submitted_at.isoformat(),
        "proposed_edits": pending.proposed_edits.model_dump(mode="json"),
        "comments": pending.comments,
    }
    if owner:
        payload["requester_login"] = pending.requester.login_at_time
        payload["requester_hf_user_id"] = pending.requester.hf_user_id
    payload["requester_role"] = (
        pending.requester.role.value
        if hasattr(pending.requester.role, "value")
        else str(pending.requester.role)
    )
    return payload


@requests_bp.route("/admin/request/<slug>", methods=["GET"])
@require_role(Role.MAINTAINER, Role.OWNER)
def get_pending(user, slug: str):
    pending = pending_requests_service.get(slug)
    if pending is None:
        return jsonify({"error": "no pending request for this reciter"}), 404
    owner = permissions.is_owner(user)
    resp = jsonify(_pending_to_payload(pending, owner=owner))
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------------------------------------------------------------------------
# Admin: reject (soft / hard)
# ---------------------------------------------------------------------------


def _reject(user, slug: str, event: str):
    body = request.get_json(silent=True) or {}
    reason, err = validate_reason(body)
    if err is not None:
        return err
    try:
        new_row = state_service.transition(
            slug, event, actor=actor_for(user), reason=reason,
        )
    except state_service.UnknownReciter:
        return jsonify({"error": "unknown reciter"}), 404
    except state_service.NotAuthorizedForTransition as e:
        return jsonify({"error": str(e)}), 403
    except state_service.InvalidTransition as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "slug": slug, "state": new_row.state.value})


@requests_bp.route("/admin/request/<slug>/reject-soft", methods=["POST"])
@require_same_origin
@require_role(Role.MAINTAINER, Role.OWNER)
def reject_soft(user, slug: str):
    return _reject(user, slug, "reciter.request_rejected_soft")


@requests_bp.route("/admin/request/<slug>/reject-hard", methods=["POST"])
@require_same_origin
@require_role(Role.MAINTAINER, Role.OWNER)
def reject_hard(user, slug: str):
    return _reject(user, slug, "reciter.request_rejected_hard")


# ---------------------------------------------------------------------------
# Owner: undiscard
# ---------------------------------------------------------------------------


@requests_bp.route("/admin/reciter/<slug>/undiscard", methods=["POST"])
@require_same_origin
@require_role(Role.OWNER)
def undiscard(user, slug: str):
    body = request.get_json(silent=True) or {}
    reason, err = validate_reason(body)
    if err is not None:
        return err
    try:
        new_row = state_service.transition(
            slug, "reciter.undiscarded", actor=actor_for(user), reason=reason,
        )
    except state_service.UnknownReciter:
        return jsonify({"error": "unknown reciter"}), 404
    except state_service.NotAuthorizedForTransition as e:
        return jsonify({"error": str(e)}), 403
    except state_service.InvalidTransition as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({
        "ok": True,
        "slug": slug,
        "state": new_row.state.value,
        "visibility": new_row.visibility.value,
    })
