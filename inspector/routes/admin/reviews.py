"""Admin Reviews-tab endpoints (maintainer/owner only).

- ``GET /api/admin/reviews/list``  master list across the four review buckets
  (Marked ready, Under review, Published, Available for review).

Read-only, so no ``@require_same_origin``.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from scripts.lib.schemas import Role

from services.admin import reviews as reviews_service

from utils.decorators import require_role

admin_reviews_bp = Blueprint("admin_reviews", __name__, url_prefix="/api/admin")


@admin_reviews_bp.route("/reviews/list")
@require_role(Role.MAINTAINER, Role.OWNER)
def list_reviews(user):
    return jsonify(reviews_service.list_reviews())
