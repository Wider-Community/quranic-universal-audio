"""Access admin endpoints (/api/admin/access/*).

Backend-only in Phase 3 — the admin dashboard UI lands in Phase 7. Three
routes mirror the ``services/access.py`` mutation surface:

- ``POST /api/admin/access/grant``   — owner-only for OWNER role; maintainer+
                                       for MAINTAINER role
- ``POST /api/admin/access/revoke``  — maintainer+; OWNER member can only
                                       be revoked by another OWNER
- ``POST /api/admin/access/update``  — login-cache refresh / role tier change

Revoke side effect (Phase 3 design): if the revoked user holds any
UNDER_REVIEW claim, those claims are auto-released as part of the same
request. Audit log captures both ``access.role_revoked`` and (one or
more) ``reciter.released`` events.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from scripts.lib.schemas import Actor, ReciterState, Role

from services import permissions

from routes._admin_helpers import (
    MIN_REASON_CHARS as _MIN_REASON_CHARS,
    actor_for as _actor_for,
    require_role_or_403 as _require_role_or_403,
    require_signed_in_or_401 as _require_signed_in_or_401,
    validate_reason as _validate_reason,
)

from services import access as access_service
from services import state as state_service

from utils.decorators import require_same_origin

logger = logging.getLogger(__name__)

access_admin_bp = Blueprint("access_admin", __name__, url_prefix="/api/admin/access")


def _force_release_active_claims(hf_user_id: str, *, revoking_actor: Actor, reason: str) -> list[str]:
    """Release every UNDER_REVIEW claim held by ``hf_user_id``.

    Returns the list of slugs released. Audited as one ``reciter.released``
    event per slug. Skips errors on individual rows (logged) to avoid
    blocking the revoke when one transition fails.
    """
    released_slugs: list[str] = []
    for row in state_service.all_rows():
        if (row.state == ReciterState.UNDER_REVIEW
                and row.assignee_hf_id == hf_user_id):
            try:
                state_service.transition(
                    row.slug,
                    "reciter.released",
                    actor=revoking_actor,
                    reason=f"Auto-release: role revoked. {reason}",
                )
                released_slugs.append(row.slug)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "auto-release on revoke failed for slug=%s: %s",
                    row.slug, e,
                )
    return released_slugs


@access_admin_bp.route("/grant", methods=["POST"])
@require_same_origin
def access_grant():
    user, err = _require_signed_in_or_401()
    if err is not None:
        return err

    body = request.get_json(silent=True) or {}
    hf_user_id = (body.get("hf_user_id") or "").strip()
    login = (body.get("login") or "").strip()
    role_raw = (body.get("role") or "").strip()
    if not hf_user_id or not login or not role_raw:
        return jsonify({"error": "hf_user_id, login, role are required"}), 400
    try:
        role = Role(role_raw)
    except ValueError:
        return jsonify({"error": f"unknown role {role_raw!r}"}), 400

    # access.grant() also enforces this, but we surface the 403 here for a
    # cleaner client experience (skip the validation path).
    if role == Role.OWNER:
        err_resp = _require_role_or_403(user, Role.OWNER)
    else:
        err_resp = _require_role_or_403(user, Role.MAINTAINER, Role.OWNER)
    if err_resp is not None:
        return err_resp

    reason, err = _validate_reason(body)
    if err is not None:
        return err

    try:
        member = access_service.grant(
            hf_user_id=hf_user_id,
            login=login,
            role=role,
            actor=_actor_for(user),
            reason=reason,
        )
    except access_service.MemberAlreadyActive as e:
        return jsonify({"error": str(e)}), 409
    except access_service.NotAuthorized as e:
        return jsonify({"error": str(e)}), 403
    except access_service.AccessError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "member": member.model_dump(mode="json")})


@access_admin_bp.route("/revoke", methods=["POST"])
@require_same_origin
def access_revoke():
    user, err = _require_signed_in_or_401()
    if err is not None:
        return err
    err_resp = _require_role_or_403(user, Role.MAINTAINER, Role.OWNER)
    if err_resp is not None:
        return err_resp

    body = request.get_json(silent=True) or {}
    hf_user_id = (body.get("hf_user_id") or "").strip()
    if not hf_user_id:
        return jsonify({"error": "hf_user_id is required"}), 400
    reason, err = _validate_reason(body)
    if err is not None:
        return err

    actor = _actor_for(user)
    try:
        member = access_service.revoke(
            hf_user_id=hf_user_id, actor=actor, reason=reason,
        )
    except access_service.NotAuthorized as e:
        return jsonify({"error": str(e)}), 403
    except access_service.MemberNotFound:
        return jsonify({"error": f"member {hf_user_id} not found"}), 404

    # Side effect: force-release any active claims this user holds. Audit
    # log captures access.role_revoked already (above) + one
    # reciter.released per slug below.
    released_slugs = _force_release_active_claims(
        hf_user_id, revoking_actor=actor, reason=reason,
    )

    return jsonify({
        "ok": True,
        "member": member.model_dump(mode="json"),
        "auto_released_slugs": released_slugs,
    })


@access_admin_bp.route("/update", methods=["POST"])
@require_same_origin
def access_update():
    user, err = _require_signed_in_or_401()
    if err is not None:
        return err
    err_resp = _require_role_or_403(user, Role.MAINTAINER, Role.OWNER)
    if err_resp is not None:
        return err_resp

    body = request.get_json(silent=True) or {}
    hf_user_id = (body.get("hf_user_id") or "").strip()
    if not hf_user_id:
        return jsonify({"error": "hf_user_id is required"}), 400

    login = body.get("login")
    role_raw = body.get("role")
    role: Role | None = None
    if role_raw:
        try:
            role = Role(role_raw)
        except ValueError:
            return jsonify({"error": f"unknown role {role_raw!r}"}), 400

    # Reason is optional for update (login refresh doesn't need a paper
    # trail beyond the actor) but if it's set, enforce min length.
    raw_reason = body.get("reason")
    if raw_reason is not None and (raw_reason or "").strip():
        reason = permissions.normalize_reason(raw_reason)
        if reason is None:
            return jsonify({
                "error": f"reason must be at least {_MIN_REASON_CHARS} characters",
            }), 400
    else:
        reason = None

    try:
        member = access_service.update(
            hf_user_id=hf_user_id,
            actor=_actor_for(user),
            login=login,
            role=role,
            reason=reason,
        )
    except access_service.NotAuthorized as e:
        return jsonify({"error": str(e)}), 403
    except access_service.MemberNotFound:
        return jsonify({"error": f"member {hf_user_id} not found"}), 404
    return jsonify({"ok": True, "member": member.model_dump(mode="json")})
