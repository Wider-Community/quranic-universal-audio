"""Admin Reviews-tab endpoints (maintainer/owner only).

- ``GET  /api/admin/reviews/list``               master list across the four
                                                 review buckets.
- ``GET  /api/admin/reviews/<slug>``             per-slug detail for the
                                                 General drawer (current
                                                 claim, history, timeline,
                                                 job ids, flagged-issue count).
- ``GET  /api/admin/reviews/unviewed-count``     per-caller marked-ready
                                                 unread count (polled by the
                                                 admin entry-button dot).
- ``POST /api/admin/reviews/<slug>/view``        advance the caller's
                                                 ``viewed_at`` for ``slug``
                                                 (fired on first drawer open).
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from qua_shared.schemas import TsJobSettings
from routes._admin_helpers import require_capability_or_403
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
    """Launch the in-container MFA timestamps job for a reciter.

    Two valid entry states (same route, same caps):

    - **First publish** — ``under_review`` + ``marked_ready``. On success the
      reciter is auto-released (``reciter.published``). Surfaced from the Reviews
      tab.
    - **Regenerate** — already ``released``. On success the reciter stays
      released; its HF/GH releases are stamped stale so the operator re-publishes
      (``reciter.ts_regenerated``). Surfaced from the Releases tab.

    Any other state (catalogued / awaiting_alignment / awaiting_review /
    under_review-without-mark-ready) has nothing to publish → 409. Generating
    timestamps IS publishing, so the caller must also hold ``reciter.publish``
    (checked inline — a second ``@require_capability`` decorator can't stack, it
    would inject ``user`` twice).

    Single-flight: rejects (409) if a job for ``slug`` is already running —
    two jobs would race the same ``timestamps/`` shards. Does NOT transition
    the reciter at launch; the launched job id is linked via
    ``timestamps_job_ids``. Returns 202 with ``{job_id, url}``.
    """
    row = state_service.get_row(slug)
    if row is None:
        return jsonify({"error": "unknown slug"}), 404
    is_first_publish = row.state.value == "under_review" and row.marked_ready
    is_regen = row.state.value == "released"
    if not (is_first_publish or is_regen):
        return jsonify(
            {
                "error": "timestamps can only be generated for a marked-ready "
                "reciter (first publish) or an already-released reciter "
                "(regenerate)",
                "state": row.state.value,
            }
        ), 409
    err = require_capability_or_403(user, "reciter.publish")
    if err is not None:
        return err
    existing = ts_jobs.running_job_for(slug)
    if existing:
        return jsonify({"error": "a timestamps job is already running", "job_id": existing}), 409
    body = request.get_json(silent=True) or {}
    try:
        settings = _parse_ts_settings(body)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    # Public URL root for the job's completion callback. Deployed: ProxyFix
    # makes this the real https Space URL; dev: localhost (unreachable by the
    # job — the poll fallback releases instead). launch() only uses it when a
    # webhook secret is configured.
    webhook_base = request.url_root
    try:
        result = ts_jobs.launch(slug, settings=settings, webhook_base=webhook_base)
    except Exception as exc:  # surfaced to the drawer
        return jsonify({"error": str(exc)}), 502
    return jsonify(result), 202


def _parse_ts_settings(body: dict) -> TsJobSettings:
    """Validate + normalize the launch form body into ``TsJobSettings``.

    Beams = [alignment_beam, *probe_beams] (deduped, order-preserving). Raises
    ``ValueError`` with a user-facing message on any invalid field.
    """
    beam = body.get("beam", 50)
    probe = body.get("probe_beams") or []
    if not isinstance(beam, int) or beam <= 0:
        raise ValueError("beam must be a positive integer")
    if not isinstance(probe, list) or not all(isinstance(b, int) and b > 0 for b in probe):
        raise ValueError("probe_beams must be a list of positive integers")
    beams: list[int] = []
    for b in [beam, *probe]:
        if b not in beams:
            beams.append(b)
    workers = body.get("workers")
    if workers is not None and (not isinstance(workers, int) or not 1 <= workers <= 64):
        raise ValueError("workers must be an integer in 1..64")
    chapters_raw = body.get("chapters")
    chapters: list[int] | None = None
    if chapters_raw is not None:
        if not isinstance(chapters_raw, list) or not all(
            isinstance(c, int) and 1 <= c <= 114 for c in chapters_raw
        ):
            raise ValueError("chapters must be a list of integers in 1..114")
        chapters = sorted(set(chapters_raw))
        if not chapters:
            chapters = None  # empty list = full reciter
    try:
        return TsJobSettings(
            beams=beams,
            persist_audio=bool(body.get("persist_audio", False)),
            gen_peaks=bool(body.get("gen_peaks", False)),
            chapters=chapters,
            workers=workers,
            flavor=body.get("flavor") or None,
            timeout=body.get("timeout") or None,
            batch_size=body.get("batch_size") or None,
            download_workers=body.get("download_workers") or None,
        )
    except ValidationError as exc:
        raise ValueError(f"invalid settings: {exc.errors()[0].get('msg', exc)}") from exc


@admin_reviews_bp.route("/reciters/<slug>/jobs/<job_id>")
@require_capability("reviews.generate_timestamps")
def job_status(user, slug, job_id):
    """Live status + bounded log tail for a launched job (HF is authoritative).

    Reciter-scoped: the durable record lives at ``reciters/<slug>/jobs/ts/`` so
    the slug is needed to read/backstop it (the drawer always has it)."""
    try:
        return jsonify(ts_jobs.job_status(slug, job_id))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@admin_reviews_bp.route("/reciters/<slug>/jobs/<job_id>/cancel", methods=["POST"])
@require_same_origin
@require_capability("reviews.generate_timestamps")
def cancel_job(user, slug, job_id):
    """Cancel an in-flight timestamps job for ``slug``.

    Same gate as launching (``reviews.generate_timestamps``) — anyone who can
    start a job can stop it. Returns 200 on success with the reconciled
    status, 404 if the slug is unknown, 502 if the HF API call failed (the
    job stays in whatever state HF reports — caller can retry)."""
    if state_service.get_row(slug) is None:
        return jsonify({"error": "unknown slug"}), 404
    try:
        result = ts_jobs.cancel_job(slug, job_id)
    except Exception as exc:  # surfaced to the drawer
        return jsonify({"error": str(exc)}), 502
    if not result.get("canceled"):
        return jsonify({"error": result.get("reason", "cancel failed")}), 502
    return jsonify(result)


@admin_reviews_bp.route("/reciters/<slug>/jobs/<job_id>/record")
@require_capability("reviews.generate_timestamps")
def job_record(user, slug, job_id):
    """Persisted record (settings + status + full logs) for one past job."""
    rec = ts_jobs.read_job_record(slug, job_id)
    if rec is None:
        return jsonify({"error": "no record for job"}), 404
    return jsonify(rec)


@admin_reviews_bp.route("/reciters/<slug>/ts-jobs")
@require_capability("reviews.generate_timestamps")
def reciter_ts_jobs(user, slug):
    """Persisted timestamps-job records for ``slug`` (newest first)."""
    if state_service.get_row(slug) is None:
        return jsonify({"error": "unknown slug"}), 404
    return jsonify({"jobs": ts_jobs.list_job_records(slug)})
