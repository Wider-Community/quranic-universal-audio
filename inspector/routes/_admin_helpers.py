"""Shared helpers for admin + claim routes.

These live here (not in ``utils/decorators.py``) because they return Flask
``Response`` tuples — they're route-layer plumbing, not generic utilities.

Domain-level predicates (role checks, reason validation) live in
``services/permissions.py``; this module wraps those predicates in HTTP
error contracts (401 / 403 / 400 tuples).
"""

from __future__ import annotations

from flask import jsonify

from scripts.lib.schemas import Actor, Role

from services import auth as auth_service
from services import permissions


# Re-exported for back-compat with imports of ``MIN_REASON_CHARS`` from this
# module. The canonical definition lives in ``services/permissions.py``.
MIN_REASON_CHARS = permissions.MIN_REASON_CHARS


def require_signed_in_or_401():
    """Return ``(user, None)`` for signed-in or ``(None, (resp, 401))``."""
    user = auth_service.current_user()
    if user is None:
        return None, (jsonify({"error": "authentication required"}), 401)
    return user, None


def require_role_or_403(user, *allowed: Role):
    """Return ``None`` if user's role is in ``allowed``, else an error tuple."""
    if not permissions.has_role(user, *allowed):
        return jsonify({"error": "insufficient role for this action"}), 403
    return None


def actor_for(user) -> Actor:
    return Actor(
        hf_user_id=user.hf_user_id,
        login_at_time=user.login,
        role=permissions.role_of(user).value,
    )


def validate_reason(body: dict, *, required: bool = True):
    """Return ``(reason_str, None)`` or ``(None, (resp, 400))``.

    When ``required=True`` and the reason is missing/short, returns a 400.
    When ``required=False``, empty/short reasons return ``("", None)`` —
    callers branch on the empty string to mean "no reason supplied."
    """
    raw = body.get("reason") if body else None
    norm = permissions.normalize_reason(raw)
    if required and norm is None:
        return None, (
            jsonify({
                "error": f"reason must be at least {MIN_REASON_CHARS} characters",
            }),
            400,
        )
    return (norm or ""), None


def row_to_dict(row) -> dict:
    return row.model_dump(mode="json")
