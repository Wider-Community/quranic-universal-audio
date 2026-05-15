"""Admin reconcile endpoint — manual trigger for the auto-detect reconciler.

Useful for dev (where the background loop is off by default) and as a
debugging backstop in deployed envs ("did the pipeline really finish?").
Synchronous: returns the count of transitions fired.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from scripts.lib.schemas import Role

from services import auto_detect as auto_detect_service

from utils.decorators import require_role, require_same_origin


admin_reconcile_bp = Blueprint("admin_reconcile", __name__, url_prefix="/api/admin")


@admin_reconcile_bp.route("/reconcile", methods=["POST"])
@require_same_origin
@require_role(Role.MAINTAINER, Role.OWNER)
def reconcile(user):  # noqa: ARG001 — user injected by @require_role
    fired = auto_detect_service.reconcile_once()
    return jsonify({"ok": True, "fired_count": fired})
