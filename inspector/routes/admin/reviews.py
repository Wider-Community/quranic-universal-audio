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

from flask import Blueprint, jsonify, request

from services.admin import reviews as reviews_service
from services.admin import timestamps_jobs as ts_jobs
from services.state import state as state_service

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


@admin_reviews_bp.route("/generate-timestamps/<slug>", methods=["POST"])
@require_same_origin
@require_capability("reviews.generate_timestamps")
def generate_timestamps(user, slug):
    """Launch the in-container MFA timestamps job for an under-review reciter.

    Single-flight: rejects (409) if a job for ``slug`` is already running —
    two jobs would race the same ``timestamps/`` shards. Does NOT transition
    the reciter; the launched job id is linked via ``timestamps_job_ids``.
    Returns 202 with ``{job_id, url}``.
    """
    if state_service.get_row(slug) is None:
        return jsonify({"error": "unknown slug"}), 404
    existing = ts_jobs.running_job_for(slug)
    if existing:
        return jsonify({"error": "a timestamps job is already running",
                        "job_id": existing}), 409
    body = request.get_json(silent=True) or {}
    beams = body.get("beams")
    if beams is not None and not (
        isinstance(beams, list) and beams and all(isinstance(b, int) for b in beams)
    ):
        return jsonify({"error": "beams must be a non-empty list of ints"}), 400
    try:
        result = ts_jobs.launch(slug, beams=beams)
    except Exception as exc:  # surfaced to the drawer
        return jsonify({"error": str(exc)}), 502
    return jsonify(result), 202


@admin_reviews_bp.route("/jobs/<job_id>")
@require_capability("reviews.generate_timestamps")
def job_status(user, job_id):
    """Live status + bounded log tail for a launched job (HF is authoritative)."""
    try:
        return jsonify(ts_jobs.job_status(job_id))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
