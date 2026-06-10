"""Admin Jobs-tab endpoints — the unified view over every job kind.

- ``GET /api/admin/jobs``         the unified list (store ∪ live HF jobs),
                                  deduped + newest-first. Cap-gated by
                                  ``reviews.view``.
- ``GET /api/admin/jobs/detail``  one job's full record for the drawer
                                  (``?kind=&job_id=&slug=``). ``reviews.view``.

Cancel reuses ``POST /api/admin/release-jobs/<job_id>/cancel`` (kind-generic,
per-kind cap gates) in ``routes/admin/releases.py`` — not re-declared here.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from qua_shared.schemas import JobsListResponse
from services.admin.jobs import registry
from utils.decorators import require_capability

log = logging.getLogger("inspector")

admin_jobs_bp = Blueprint("admin_jobs", __name__, url_prefix="/api/admin")


@admin_jobs_bp.route("/jobs", methods=["GET"])
@require_capability("reviews.view")
def list_jobs(user):
    """Unified job list across all kinds (running + historical)."""
    jobs = registry.list_all_jobs()
    running = sum(1 for j in jobs if j.status == "running")
    payload = JobsListResponse(jobs=jobs, running_count=running)
    return jsonify(payload.model_dump(mode="json"))


@admin_jobs_bp.route("/jobs/detail", methods=["GET"])
@require_capability("reviews.view")
def job_detail(user):
    """One job's full record for the detail drawer."""
    kind = (request.args.get("kind") or "").strip()
    job_id = (request.args.get("job_id") or "").strip()
    slug = (request.args.get("slug") or "").strip() or None
    if not kind or not job_id:
        return jsonify({"error": "kind and job_id are required"}), 400
    rec = registry.job_detail(kind, job_id, slug)
    if rec is None:
        return jsonify({"error": "job record not found"}), 404
    return jsonify(rec.model_dump(mode="json"))
