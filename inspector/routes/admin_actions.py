"""Admin override endpoints (/api/admin/*).

Phase 4 backend surface. Each route is a thin wrapper around a single
``state.transition`` call gated by maintainer+ role. State-machine
handlers (`_h_force_released`, `_h_reassigned`, `_h_force_set_state`,
`_h_merge_rejected`) own all precondition + invariant checks; routes
just authenticate, validate body shape, and dispatch.

The ``users/lookup`` endpoint is the only one that touches the network —
a thin proxy over HF's public ``/api/users/<login>/overview`` so the
reassign route (and a future admin UI) can resolve a free-text login to
a stable ``hf_user_id`` before persisting it as an assignee.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from scripts.lib.schemas import ReciterState, Role

from routes._admin_helpers import (
    actor_for,
    require_role_or_403,
    require_signed_in_or_401,
    row_to_dict,
    validate_reason,
)

from services import hf_users
from services import state as state_service

from utils.decorators import require_same_origin

logger = logging.getLogger(__name__)

admin_actions_bp = Blueprint("admin_actions", __name__, url_prefix="/api/admin")


def _require_maintainer_or_above():
    """Auth + maintainer-or-owner gate. Returns ``(user, None)`` or
    ``(None, (resp, status))``.
    """
    user, err = require_signed_in_or_401()
    if err is not None:
        return None, err
    err_resp = require_role_or_403(user, Role.MAINTAINER, Role.OWNER)
    if err_resp is not None:
        return None, err_resp
    return user, None


@admin_actions_bp.route("/claim/force-release/<slug>", methods=["POST"])
@require_same_origin
def force_release(slug: str):
    user, err = _require_maintainer_or_above()
    if err is not None:
        return err

    body = request.get_json(silent=True) or {}
    reason, err = validate_reason(body)
    if err is not None:
        return err

    before = state_service.get_row(slug)
    original_assignee = before.assignee_hf_id if before else None

    new_row = state_service.transition(
        slug,
        "claim.force_released",
        actor=actor_for(user),
        reason=reason,
    )
    return jsonify({
        "row": row_to_dict(new_row),
        "original_assignee_hf_id": original_assignee,
    })


@admin_actions_bp.route("/claim/reassign/<slug>", methods=["POST"])
@require_same_origin
def reassign(slug: str):
    user, err = _require_maintainer_or_above()
    if err is not None:
        return err

    body = request.get_json(silent=True) or {}
    to_login = (body.get("to_login") or "").strip()
    if not to_login:
        return jsonify({"error": "to_login is required"}), 400
    reason, err = validate_reason(body)
    if err is not None:
        return err

    try:
        target = hf_users.lookup(to_login)
    except hf_users.HfUserLookupError as e:
        logger.warning("reassign: hf lookup failed: %s", e)
        return jsonify({"error": "HF user lookup failed; retry"}), 502
    if target is None:
        return jsonify({
            "error": f"unknown HF login {to_login!r}",
            "unknown_login": to_login,
        }), 400

    before = state_service.get_row(slug)
    if before is not None and before.assignee_hf_id == target.hf_user_id:
        return jsonify({
            "error": f"already assigned to {target.login!r}",
        }), 400

    new_row = state_service.transition(
        slug,
        "claim.reassigned",
        actor=actor_for(user),
        payload={
            "new_assignee_hf_id": target.hf_user_id,
            "new_assignee_login": target.login,
        },
        reason=reason,
    )
    return jsonify({
        "row": row_to_dict(new_row),
        "to_user": {
            "hf_user_id": target.hf_user_id,
            "login": target.login,
            "fullname": target.fullname,
            "avatar_url": target.avatar_url,
        },
    })


@admin_actions_bp.route("/state/force-set/<slug>", methods=["POST"])
@require_same_origin
def force_set_state(slug: str):
    user, err = _require_maintainer_or_above()
    if err is not None:
        return err

    body = request.get_json(silent=True) or {}
    to_state_raw = (body.get("to_state") or "").strip()
    if not to_state_raw:
        return jsonify({"error": "to_state is required"}), 400
    try:
        ReciterState(to_state_raw)
    except ValueError:
        return jsonify({"error": f"unknown to_state {to_state_raw!r}"}), 400
    reason, err = validate_reason(body)
    if err is not None:
        return err

    new_row = state_service.transition(
        slug,
        "admin.force_set_state",
        actor=actor_for(user),
        payload={"to_state": to_state_raw},
        reason=reason,
    )
    return jsonify({"row": row_to_dict(new_row)})


@admin_actions_bp.route("/send-back/<slug>", methods=["POST"])
@require_same_origin
def send_back(slug: str):
    user, err = _require_maintainer_or_above()
    if err is not None:
        return err

    body = request.get_json(silent=True) or {}
    reason, err = validate_reason(body)
    if err is not None:
        return err

    new_row = state_service.transition(
        slug,
        "reciter.merge_rejected",
        actor=actor_for(user),
        reason=reason,
    )
    return jsonify({"row": row_to_dict(new_row)})


@admin_actions_bp.route("/users/lookup", methods=["POST"])
@require_same_origin
def users_lookup():
    _user, err = _require_maintainer_or_above()
    if err is not None:
        return err

    body = request.get_json(silent=True) or {}
    login = (body.get("login") or "").strip()
    if not login:
        return jsonify({"error": "login is required"}), 400

    try:
        target = hf_users.lookup(login)
    except hf_users.HfUserLookupError as e:
        logger.warning("users/lookup: hf request failed: %s", e)
        return jsonify({"error": "HF user lookup failed; retry"}), 502
    if target is None:
        return jsonify({"error": f"HF user {login!r} not found"}), 404

    return jsonify({
        "hf_user_id": target.hf_user_id,
        "login": target.login,
        "fullname": target.fullname,
        "avatar_url": target.avatar_url,
    })
