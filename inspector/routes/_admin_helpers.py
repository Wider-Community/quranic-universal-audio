"""Shared helpers for admin + claim routes.

These live here (not in ``utils/decorators.py``) because they return Flask
``Response`` tuples — they're route-layer plumbing, not generic utilities.
"""

from __future__ import annotations

from flask import jsonify

from scripts.lib.schemas import Actor, Role

from services import auth as auth_service


MIN_REASON_CHARS = 10


def require_signed_in_or_401():
    """Return ``(user, None)`` for signed-in or ``(None, (resp, 401))``."""
    user = auth_service.current_user()
    if user is None:
        return None, (jsonify({"error": "authentication required"}), 401)
    return user, None


def require_role_or_403(user, *allowed: Role):
    """Return ``None`` if user's role is in ``allowed``, else an error tuple."""
    if Role(user.role) not in allowed:
        return jsonify({"error": "insufficient role for this action"}), 403
    return None


def actor_for(user) -> Actor:
    role_val = user.role.value if hasattr(user.role, "value") else user.role
    return Actor(
        hf_user_id=user.hf_user_id,
        login_at_time=user.login,
        role=role_val,
    )


def validate_reason(body: dict, *, required: bool = True):
    """Return ``(reason_str, None)`` or ``(None, (resp, 400))``."""
    reason = (body.get("reason") or "").strip() if body else ""
    if required and len(reason) < MIN_REASON_CHARS:
        return None, (
            jsonify({
                "error": f"reason must be at least {MIN_REASON_CHARS} characters",
            }),
            400,
        )
    return reason, None


def row_to_dict(row) -> dict:
    return row.model_dump(mode="json")
