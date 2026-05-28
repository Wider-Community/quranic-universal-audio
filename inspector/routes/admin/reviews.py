"""Admin Reviews-tab endpoints (maintainer/owner only).

- ``GET /api/admin/reviews/list``                master list across the four
                                                 review buckets.
- ``GET /api/admin/reviews/<slug>``              per-slug detail for the
                                                 General drawer (current
                                                 claim, history, timeline,
                                                 job ids).
- ``GET /api/admin/reviews/<slug>/validation``   lazy-fetched validation
                                                 category counts (expensive —
                                                 walks the bucket).

All read-only, so no ``@require_same_origin``.
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


@admin_reviews_bp.route("/reviews/<slug>")
@require_role(Role.MAINTAINER, Role.OWNER)
def review_detail(user, slug):
    detail = reviews_service.get_review_detail(slug)
    if detail is None:
        return jsonify({"error": "unknown slug"}), 404
    return jsonify(detail)


@admin_reviews_bp.route("/reviews/<slug>/validation")
@require_role(Role.MAINTAINER, Role.OWNER)
def review_validation(user, slug):
    return jsonify(reviews_service.get_review_validation(slug))
