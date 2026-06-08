"""Per-user "My Notifications" routes (``/api/me/notifications``).

Backs the Dashboard notifications rail. Every route requires a signed-in user
(401 anon) and is scoped to that user — a notification can only be listed,
dismissed, or restored by its owner. Notifications are materialized server-side
by ``services.notifications`` (lifecycle transitions + segment-flag replies);
these routes are read + dismiss/restore only.

Opening the active list stamps ``seen_at`` (clearing the unread badge) in the
same durable transaction. Writes wrap ``sync.durable_transaction``; the
read-only archived list does not.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify

from services import auth as auth_service
from services.db import repo_notifications
from services.db import sync as _sync
from utils.decorators import require_same_origin

logger = logging.getLogger(__name__)

notifications_bp = Blueprint("notifications", __name__, url_prefix="/api/me/notifications")


@notifications_bp.route("", methods=["GET"])
def list_notifications():
    """Active (un-dismissed) notifications, newest-first, + unread count.

    Marks them seen in the same transaction so the badge clears on open."""
    user = auth_service.current_user()
    if user is None:
        return jsonify({"error": "authentication required"}), 401
    try:
        items = repo_notifications.list_active(user.hf_user_id)
        unread = repo_notifications.unread_count(user.hf_user_id)
        if unread:
            with _sync.durable_transaction():
                repo_notifications.mark_seen(user.hf_user_id)
    except Exception:  # noqa: BLE001
        logger.exception("notifications.list failed for %s", user.hf_user_id)
        return jsonify({"error": "failed to load notifications"}), 500
    return jsonify({"notifications": items, "unread": unread})


@notifications_bp.route("/archived", methods=["GET"])
def list_archived():
    """Archived (dismissed) notifications, most-recently-dismissed-first."""
    user = auth_service.current_user()
    if user is None:
        return jsonify({"error": "authentication required"}), 401
    try:
        items = repo_notifications.list_archived(user.hf_user_id)
    except Exception:  # noqa: BLE001
        logger.exception("notifications.archived failed for %s", user.hf_user_id)
        return jsonify({"error": "failed to load notifications"}), 500
    return jsonify({"notifications": items})


@notifications_bp.route("/<int:notification_id>/dismiss", methods=["POST"])
@require_same_origin
def dismiss(notification_id):
    """Archive one active notification owned by the caller. 404 if not theirs."""
    user = auth_service.current_user()
    if user is None:
        return jsonify({"error": "authentication required"}), 401
    try:
        with _sync.durable_transaction():
            ok = repo_notifications.dismiss(notification_id, user.hf_user_id)
    except Exception:  # noqa: BLE001
        logger.exception("notifications.dismiss failed for %s/%s", user.hf_user_id, notification_id)
        return jsonify({"error": "failed to dismiss notification"}), 500
    if not ok:
        return jsonify({"error": "notification not found"}), 404
    return ("", 204)


@notifications_bp.route("/<int:notification_id>/restore", methods=["POST"])
@require_same_origin
def restore(notification_id):
    """Move one archived notification back to active. 404 if not theirs."""
    user = auth_service.current_user()
    if user is None:
        return jsonify({"error": "authentication required"}), 401
    try:
        with _sync.durable_transaction():
            ok = repo_notifications.restore(notification_id, user.hf_user_id)
    except Exception:  # noqa: BLE001
        logger.exception("notifications.restore failed for %s/%s", user.hf_user_id, notification_id)
        return jsonify({"error": "failed to restore notification"}), 500
    if not ok:
        return jsonify({"error": "notification not found"}), 404
    return ("", 204)
