"""Admin Reviews-tab endpoints (maintainer/owner only).

- ``GET  /api/admin/reviews/list``               master list across the four
                                                 review buckets.
- ``GET  /api/admin/reviews/<slug>``             per-slug detail for the
                                                 General drawer (current
                                                 claim, history, timeline,
                                                 job ids).
- ``GET  /api/admin/reviews/<slug>/validation``  lazy-fetched validation
                                                 category counts (expensive —
                                                 walks the bucket).
- ``GET  /api/admin/reviews/unviewed-count``     per-caller marked-ready
                                                 unread count (polled by the
                                                 admin entry-button dot).
- ``POST /api/admin/reviews/<slug>/view``        advance the caller's
                                                 ``viewed_at`` for ``slug``
                                                 (fired on first drawer open).
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from services.admin import reviews as reviews_service

from utils.decorators import require_capability, require_same_origin

admin_reviews_bp = Blueprint("admin_reviews", __name__, url_prefix="/api/admin")


@admin_reviews_bp.route("/reviews/list")
@require_capability("reviews.view")
def list_reviews(user):
    return jsonify(reviews_service.list_reviews(caller_hf_id=user.hf_user_id))


@admin_reviews_bp.route("/reviews/unviewed-count", methods=["GET"])
@require_capability("reviews.view")
def reviews_unviewed_count(user):
    """Marked-ready entries the caller hasn't viewed — drives the entry-button
    dot + the Reviews tab pill. Polled, so never cached."""
    resp = jsonify(
        {"count": reviews_service.unviewed_marked_ready_count(caller_hf_id=user.hf_user_id)}
    )
    resp.headers["Cache-Control"] = "no-store"
    return resp


@admin_reviews_bp.route("/reviews/<slug>")
@require_capability("reviews.view")
def review_detail(user, slug):
    detail = reviews_service.get_review_detail(slug)
    if detail is None:
        return jsonify({"error": "unknown slug"}), 404
    return jsonify(detail)


@admin_reviews_bp.route("/reviews/<slug>/validation")
@require_capability("reviews.view")
def review_validation(user, slug):
    return jsonify(reviews_service.get_review_validation(slug))


@admin_reviews_bp.route("/reviews/<slug>/view", methods=["POST"])
@require_same_origin
@require_capability("reviews.view")
def mark_review_viewed(user, slug):
    """Mark ``slug`` viewed for the calling admin (fired on first drawer open
    of that slug in a session — General or Ops). Idempotent at the row level
    (upsert); only writes when this drawer-open is new for the slug."""
    ok = reviews_service.mark_viewed(slug, caller_hf_id=user.hf_user_id)
    if not ok:
        return jsonify({"error": "unknown slug"}), 404
    return jsonify({"ok": True})
