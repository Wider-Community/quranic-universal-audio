"""Claim / release / mark / unmark + reciter-task routes.

These endpoints mutate the bucket state file directly via
``state.transition``; no ``require_edit_lock`` here — state.py handlers
own the ownership + precondition checks and raise:

- ``InvalidTransition`` → 400 (mapped at app errorhandler).
- ``NotAuthorizedForTransition`` → 403 (mapped at app errorhandler).
- ``UnknownReciter`` → 404 (mapped at app errorhandler).

The route's job is: authenticate, do the one-claim-per-user pre-check
(application policy, not part of the state machine), build the ``Actor``,
dispatch the transition, and return the authoritative row.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify

from scripts.lib.schemas import Actor

from services import auth as auth_service
from services import predicates as predicates_service
from services import state as state_service

from utils.decorators import require_same_origin

logger = logging.getLogger(__name__)

claims_bp = Blueprint("claims", __name__, url_prefix="/api")


def _require_user_or_401():
    user = auth_service.current_user()
    if user is None:
        return None, (jsonify({"error": "authentication required"}), 401)
    return user, None


def _actor_for(user) -> Actor:
    role_val = user.role.value if hasattr(user.role, "value") else user.role
    return Actor(
        hf_user_id=user.hf_user_id,
        login_at_time=user.login,
        role=role_val,
    )


def _row_to_dict(row) -> dict:
    return row.model_dump(mode="json")


@claims_bp.route("/claim/<slug>", methods=["POST"])
@require_same_origin
def claim(slug: str):
    user, err = _require_user_or_401()
    if err is not None:
        return err

    # One-claim-per-user policy (application-level; state.py doesn't enforce).
    other = next(
        (
            r.slug for r in state_service.all_rows()
            if r.state.value == "under_review"
            and r.assignee_hf_id == user.hf_user_id
            and r.slug != slug
        ),
        None,
    )
    if other is not None:
        return jsonify({
            "error": f"already holding a claim on {other}",
            "existing_claim": other,
        }), 409

    new_row = state_service.transition(
        slug,
        "reciter.claimed",
        actor=_actor_for(user),
    )
    return jsonify(_row_to_dict(new_row))


@claims_bp.route("/release/<slug>", methods=["POST"])
@require_same_origin
def release(slug: str):
    user, err = _require_user_or_401()
    if err is not None:
        return err
    new_row = state_service.transition(
        slug,
        "reciter.released",
        actor=_actor_for(user),
    )
    return jsonify(_row_to_dict(new_row))


@claims_bp.route("/mark-ready/<slug>", methods=["POST"])
@require_same_origin
def mark_ready(slug: str):
    user, err = _require_user_or_401()
    if err is not None:
        return err
    new_row = state_service.transition(
        slug,
        "reciter.marked_ready",
        actor=_actor_for(user),
    )
    return jsonify(_row_to_dict(new_row))


@claims_bp.route("/unmark-ready/<slug>", methods=["POST"])
@require_same_origin
def unmark_ready(slug: str):
    user, err = _require_user_or_401()
    if err is not None:
        return err
    new_row = state_service.transition(
        slug,
        "reciter.unmarked_ready",
        actor=_actor_for(user),
    )
    return jsonify(_row_to_dict(new_row))


@claims_bp.route("/reciter-task/<slug>")
def reciter_task(slug: str):
    """Full row + per-user predicates. Anonymous gets predicates all false."""
    user = auth_service.current_user()
    row = state_service.get_row(slug)
    if row is None:
        return jsonify({"error": "unknown reciter"}), 404

    has_other = False
    if user is not None:
        has_other = state_service.has_other_active_claim(
            user.hf_user_id, except_slug=slug,
        )

    return jsonify({
        "row": _row_to_dict(row),
        "predicates": predicates_service.build_predicates(
            row, user, has_other_active_claim=has_other,
        ),
    })
