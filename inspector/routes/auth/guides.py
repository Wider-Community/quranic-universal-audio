"""Accordion-guide read-tracking route.

``POST /api/guides/viewed`` records that the signed-in user has opened a
validation-accordion help guide. The set of read guides (returned on
``/api/me`` as ``guides_read``) drives the FE unread border on each ``?`` and
the first-edit onboarding gate. Write-once per (view_key, user); the body's
``category`` is collapsed to its stored view key (``low_confidence_v2`` →
``low_confidence``) and validated against the allowlist before storage.

Onboarding is UX, not authz — there is no save-time enforcement (the real edit
gate stays in ``utils/decorators.require_edit_lock``). This route just records
the signal the FE reacts to.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from constants import guide_view_key
from services import auth as auth_service
from services.db import repo_guides
from services.db import sync as _sync
from utils.decorators import require_same_origin

logger = logging.getLogger(__name__)

guides_bp = Blueprint("guides", __name__, url_prefix="/api/guides")


@guides_bp.route("/viewed", methods=["POST"])
@require_same_origin
def mark_guide_viewed():
    """Record one guide as read for the calling user. 401 anon, 400 unknown."""
    user = auth_service.current_user()
    if user is None:
        return jsonify({"error": "authentication required"}), 401

    body = request.get_json(silent=True) or {}
    category = body.get("category")
    view_key = guide_view_key(category) if isinstance(category, str) else None
    if view_key is None:
        return jsonify({"error": "unknown guide category"}), 400

    try:
        with _sync.durable_transaction():
            repo_guides.record_view(user.hf_user_id, view_key)
    except Exception:  # noqa: BLE001 — surface as 500, never a silent swallow
        logger.exception("guides.viewed: failed to record view for %s", view_key)
        return jsonify({"error": "failed to record guide view"}), 500

    return ("", 204)
