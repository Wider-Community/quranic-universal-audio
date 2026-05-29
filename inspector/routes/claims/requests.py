"""Request-flow endpoints — user submit + admin review/reject + undiscard.

User-facing:
- ``POST /api/reciter/<slug>/request`` — any signed-in user can submit a
  request with proposed catalog edits + free-form comments. Transitions
  the row CATALOGUED → AWAITING_ALIGNMENT and persists the pending entry.

Admin (maintainer + owner):
- ``GET  /api/admin/request/<slug>`` — fetch one pending request payload.
  Requester actor identity is included for owners, redacted for maintainers
  (same tier-based redaction pattern as the Requests tab list endpoint).
- ``GET  /api/admin/requests?status=open|accepted|returned|discarded`` —
  Requests-tab review queue (catalog-joined, tier-redacted) + facet counts +
  the caller's unviewed-open count.
- ``GET  /api/admin/requests/unviewed-count`` — the caller's unviewed-open
  count alone (entry-button dot + tab pill when the modal is closed).
- ``POST /api/admin/requests/<id>/view`` — mark a request viewed for the
  calling admin (fired on inline expand). Per-admin, idempotent.

Owner-only:
- ``POST /api/admin/request/<slug>/reject-soft`` — send back; row returns
  to CATALOGUED. Reason ≥10 chars required.
- ``POST /api/admin/request/<slug>/reject-hard`` — discard; row goes back
  to CATALOGUED + visibility=DISCARDED. Reason ≥10 chars required.
- ``POST /api/admin/reciter/<slug>/undiscard`` — restore a discarded
  row to visibility=PUBLIC. Reason ≥10 chars required.

All POST routes stack ``@require_same_origin`` for CSRF defense on top
of ``@require_role`` for the tier check.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from scripts.lib.schemas import Actor, IntakeSubmission

from routes._admin_helpers import actor_for, validate_reason

from services import auth as auth_service
from services import pending_requests as pending_requests_service
from services import permissions
from services import state as state_service
from services.admin import intake as intake_service
from services.admin import requests as admin_requests_service
from services.auth import capabilities as cap_service
from services.auth import token_auth
from services.auth.access import NotAuthorized

from utils.decorators import require_capability, require_same_origin


requests_bp = Blueprint("requests", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# User: submit
# ---------------------------------------------------------------------------


@requests_bp.route("/reciter/<slug>/request", methods=["POST"])
@require_same_origin
@require_capability("request.submit")
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

    auto_claim = body.get("auto_claim", False)
    if not isinstance(auto_claim, bool):
        return jsonify({"error": "auto_claim must be a boolean"}), 400

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
                "auto_claim": auto_claim,
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
# User: submit intake (new combination / new reciter — slugless)
# ---------------------------------------------------------------------------


@requests_bp.route("/requests/intake", methods=["POST"])
@require_same_origin
@require_capability("request.submit")
def submit_intake(user):
    """New-combo / new-reciter contribution with an audio source (direct links
    or a playlist). Structural-validate, then record a slugless pending request.
    400 carries ``{errors, warnings}`` on blocking validation failure."""
    body = request.get_json(silent=True) or {}
    try:
        sub = IntakeSubmission.model_validate(body)
    except ValidationError as e:
        return jsonify({"error": "invalid submission", "detail": e.errors()}), 400
    try:
        rid, validation = intake_service.submit(sub, requester=actor_for(user))
    except intake_service.IntakeValidationError as e:
        return jsonify({
            "error": "validation failed",
            "errors": e.validation.errors,
            "warnings": e.validation.warnings,
        }), 400
    return jsonify({"ok": True, "id": rid, "warnings": validation.warnings})


# ---------------------------------------------------------------------------
# Admin: fetch pending
# ---------------------------------------------------------------------------


def _pending_to_payload(pending, *, owner: bool) -> dict:
    """Serialize a ``PendingRequest`` for the admin review form.

    Owners see the full requester actor identity; maintainers see only the
    role — same tier-based redaction the Requests-tab list endpoint applies.
    """
    payload = {
        "slug": pending.slug,
        "submitted_at": pending.submitted_at.isoformat(),
        "proposed_edits": pending.proposed_edits.model_dump(mode="json"),
        "comments": pending.comments,
        "auto_claim": pending.auto_claim,
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
@require_capability("request.review")
def get_pending(user, slug: str):
    pending = pending_requests_service.get(slug)
    if pending is None:
        return jsonify({"error": "no pending request for this reciter"}), 404
    # Identity disclosure is now a toggleable capability (default owner-only).
    owner = cap_service.can(user, "identity.see_actor")
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
@require_capability("request.reject_soft")
def reject_soft(user, slug: str):
    return _reject(user, slug, "reciter.request_rejected_soft")


@requests_bp.route("/admin/request/<slug>/reject-hard", methods=["POST"])
@require_same_origin
@require_capability("request.reject_hard")
def reject_hard(user, slug: str):
    return _reject(user, slug, "reciter.request_rejected_hard")


# ---------------------------------------------------------------------------
# Admin: Requests-tab list + per-admin unviewed badge
# ---------------------------------------------------------------------------


_VALID_STATUSES = ("open", "accepted", "returned", "discarded")


@requests_bp.route("/admin/requests", methods=["GET"])
@require_capability("request.review")
def list_requests(user):
    """Review-queue payload for one status facet. Tier-redacted: maintainers
    see requester role only, owners see the full identity."""
    status = request.args.get("status", "open")
    if status not in _VALID_STATUSES:
        return jsonify({"error": "invalid status"}), 400
    payload = admin_requests_service.list_requests(
        status=status,
        caller_is_owner=cap_service.can(user, "identity.see_actor"),
        caller_hf_id=user.hf_user_id,
    )
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@requests_bp.route("/admin/requests/unviewed-count", methods=["GET"])
@require_capability("request.review")
def requests_unviewed_count(user):
    """Open requests the caller hasn't viewed — drives the tab pill + the
    entry-button dot. Polled, so never cached."""
    resp = jsonify(
        {"count": admin_requests_service.unviewed_count(caller_hf_id=user.hf_user_id)}
    )
    resp.headers["Cache-Control"] = "no-store"
    return resp


@requests_bp.route("/admin/requests/<rid>/view", methods=["POST"])
@require_same_origin
@require_capability("request.review")
def mark_request_viewed(user, rid: str):
    """Mark a request viewed for the calling admin (fired on inline expand)."""
    ok = admin_requests_service.mark_viewed(rid, actor=actor_for(user))
    if not ok:
        return jsonify({"error": "unknown request"}), 404
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Owner: intake accept / probe / resolve (slugless new-combo / new-reciter)
# ---------------------------------------------------------------------------


@requests_bp.route("/admin/requests/<rid>/accept", methods=["POST"])
@require_same_origin
@require_capability("intake.accept")
def accept_intake(user, rid: str):
    """Approve an intake request + queue it for offline ingest. Body (new-reciter
    only): owner-confirmed canonical ``reciter_id``. No catalog write here —
    source/channel/slug are determined by ingest from the actual audio."""
    body = request.get_json(silent=True) or {}
    reciter_id = body.get("reciter_id")
    try:
        intake_service.accept(rid, actor=actor_for(user), reciter_id=reciter_id)
    except intake_service.NotIntakeRequest:
        return jsonify({"error": "unknown intake request"}), 404
    except intake_service.IntakeError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


def _resolve_owner_actor() -> tuple[Actor | None, tuple | None]:
    """Authorize an owner via EITHER an ``Authorization: Bearer <HF_TOKEN>``
    header (server-to-server) OR the ``inspector_session`` owner cookie.

    Returns ``(actor, None)`` for an authorized owner, or ``(None, (resp,
    status))`` for the error response. Fail closed: any whoami error rejects.

    Bearer takes precedence (the offline pipeline always sends it). Missing both
    creds → 401; an authenticated non-owner → 403.
    """
    token = token_auth.bearer_token_from_header(request.headers.get("Authorization"))
    if token is not None:
        try:
            actor = token_auth.resolve_owner_from_token(token)
        except token_auth.TokenAuthError:
            return None, (jsonify({"error": "invalid bearer token"}), 401)
        except token_auth.NotOwner:
            return None, (jsonify({"error": "owner role required"}), 403)
        return actor, None

    user = auth_service.current_user()
    if user is None:
        return None, (jsonify({"error": "authentication required"}), 401)
    if not permissions.is_owner(user):
        return None, (jsonify({"error": "owner role required"}), 403)
    return actor_for(user), None


@requests_bp.route("/admin/intake/<rid>/ingest", methods=["POST"])
def ingest_intake(rid: str):
    """Mint the catalog delivery for an accepted slugless intake + seed it into
    the alignment queue. Server-to-server (offline ingest pipeline) via a bearer
    HF token, or owner cookie from the dashboard.

    Bearer path is exempt from ``@require_same_origin`` (no browser, no CSRF
    surface); the cookie path enforces same-origin inline.
    """
    actor, err = _resolve_owner_actor()
    if err is not None:
        return err

    # CSRF defense for the cookie path only (a bearer token can't be CSRF'd —
    # the browser never auto-attaches an Authorization header cross-site).
    used_bearer = token_auth.bearer_token_from_header(
        request.headers.get("Authorization")
    ) is not None
    if not used_bearer:
        from urllib.parse import urlparse
        origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
        p = urlparse(origin)
        if not (origin and p.scheme == request.scheme and p.netloc == request.host):
            return jsonify({"error": "cross-origin request rejected"}), 403

    body = request.get_json(silent=True) or {}
    try:
        result = intake_service.ingest(rid, body, actor=actor)
    except intake_service.NotIntakeRequest:
        return jsonify({"error": "unknown intake request"}), 404
    except intake_service.IngestSlugCollision as e:
        return jsonify({"error": str(e)}), 409
    except intake_service.IngestVocabMissing as e:
        return jsonify({"error": str(e)}), 422
    except intake_service.IngestBadRequest as e:
        return jsonify({"error": str(e)}), 400
    except NotAuthorized as e:
        return jsonify({"error": str(e)}), 403
    except state_service.NotAuthorizedForTransition as e:
        return jsonify({"error": str(e)}), 403
    except state_service.InvalidTransition as e:
        return jsonify({"error": str(e)}), 400
    except intake_service.IngestError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result)


@requests_bp.route("/admin/requests/<rid>/probe", methods=["POST"])
@require_same_origin
@require_capability("intake.probe")
def probe_intake(user, rid: str):
    """Owner-triggered reachability probe of an intake request's audio source."""
    try:
        result = intake_service.probe(rid)
    except intake_service.NotIntakeRequest:
        return jsonify({"error": "unknown intake request"}), 404
    return jsonify(result.model_dump(mode="json"))


@requests_bp.route("/admin/requests/<rid>/return", methods=["POST"])
@require_same_origin
@require_capability("intake.resolve")
def return_intake(user, rid: str):
    return _resolve_intake(user, rid, "returned")


@requests_bp.route("/admin/requests/<rid>/discard", methods=["POST"])
@require_same_origin
@require_capability("intake.resolve")
def discard_intake(user, rid: str):
    return _resolve_intake(user, rid, "discarded")


def _resolve_intake(user, rid: str, status: str):
    body = request.get_json(silent=True) or {}
    reason, err = validate_reason(body)
    if err is not None:
        return err
    try:
        intake_service.resolve(rid, status=status, reason=reason, actor=actor_for(user))
    except intake_service.NotIntakeRequest:
        return jsonify({"error": "unknown intake request"}), 404
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Owner: undiscard
# ---------------------------------------------------------------------------


@requests_bp.route("/admin/reciter/<slug>/undiscard", methods=["POST"])
@require_same_origin
@require_capability("reciter.undiscard")
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
