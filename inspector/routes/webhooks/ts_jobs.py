"""Timestamps-job completion webhook (machine-to-machine, secret-gated).

The HF timestamps job POSTs here on success so the Inspector — the single
SQLite writer — publishes the reciter (``under_review`` marked_ready →
``released``). HF has no native job-completion webhook, so the job self-reports.

Auth is a shared secret in the ``X-Inspector-Job-Secret`` header compared with
``hmac.compare_digest`` against ``INSPECTOR_WEBHOOK_SECRET``. No OAuth cookie,
no ``@require_same_origin`` (the caller is a job, not a browser) — modeled on
the unauthenticated ``/healthz``. When the secret env is unset the endpoint is
disabled (503): dev relies on the ``job_status`` poll fallback instead.

The actual publish is idempotent + best-effort
(``timestamps_jobs.complete_timestamps_job``), so a double-fire with the poll
fallback, or a retry, is safe.
"""

from __future__ import annotations

import hmac
import logging
import os

from flask import Blueprint, jsonify, request

from services.admin import timestamps_jobs as ts_jobs
from services.admin.jobs import hf_publish, cut_release

log = logging.getLogger("inspector")

webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/api/webhooks")

_SECRET_HEADER = "X-Inspector-Job-Secret"
# Terminal stage strings the job may report as a clean success.
_SUCCESS = ("succeeded", "completed")


@webhooks_bp.route("/ts-job-complete", methods=["POST"])
def ts_job_complete():
    """Publish a reciter whose timestamps job just succeeded.

    Body: ``{"slug": str, "job_id": str, "status": str}``. Acts only on a
    success status; any other status is acknowledged and ignored (the panel /
    poll surfaces failures). Returns the orchestrator result.
    """
    secret = os.environ.get("INSPECTOR_WEBHOOK_SECRET", "").strip()
    if not secret:
        # Webhook disabled (no secret configured) — dev/local. Tell the caller
        # so it doesn't keep retrying; the poll fallback handles release.
        return jsonify({"error": "webhook disabled"}), 503

    provided = request.headers.get(_SECRET_HEADER, "")
    if not provided or not hmac.compare_digest(provided, secret):
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    slug = (body.get("slug") or "").strip()
    job_id = (body.get("job_id") or "").strip()
    status = (body.get("status") or "").strip().lower()
    if not slug or not job_id:
        return jsonify({"error": "slug and job_id are required"}), 400

    try:
        if status in _SUCCESS:
            # Publish the reciter (+ light the Published-bucket dot).
            result = ts_jobs.complete_timestamps_job(slug, job_id)
        else:
            # Failed/cancelled/etc. — no publish, just light the Marked-ready
            # dot so the admin knows the run finished and needs attention.
            result = ts_jobs.note_timestamps_job_failed(slug)
    except Exception as exc:  # noqa: BLE001 — surface as 502, the job may retry
        log.warning("ts-job-complete webhook for %s failed: %s", slug, exc)
        return jsonify({"error": str(exc)}), 502
    return jsonify({"ok": True, **result})


def _check_secret() -> tuple[bool, tuple]:
    """Shared auth: HMAC-compare the ``X-Inspector-Job-Secret`` header.

    Returns ``(ok, (response, status))``. When the env isn't set we 503
    (the poll fallback handles completion in dev).
    """
    secret = os.environ.get("INSPECTOR_WEBHOOK_SECRET", "").strip()
    if not secret:
        return False, (jsonify({"error": "webhook disabled"}), 503)
    provided = request.headers.get(_SECRET_HEADER, "")
    if not provided or not hmac.compare_digest(provided, secret):
        return False, (jsonify({"error": "unauthorized"}), 401)
    return True, (None, None)


@webhooks_bp.route("/hf-publish-complete", methods=["POST"])
def hf_publish_complete():
    """Record a successful HF dataset push. Idempotent on (slug, version).

    Body: ``{"slug", "job_id", "status", "version", "external_uri",
    "launched_by", "validation_summary"}``. Only acts on a success status.
    """
    ok, err = _check_secret()
    if not ok:
        return err
    body = request.get_json(silent=True) or {}
    slug = (body.get("slug") or "").strip()
    job_id = (body.get("job_id") or "").strip()
    status = (body.get("status") or "").strip().lower()
    version = (body.get("version") or "").strip() or job_id
    if not slug or not job_id:
        return jsonify({"error": "slug and job_id are required"}), 400
    if status not in _SUCCESS:
        return jsonify({"ok": True, "skipped": "non-success status"})
    try:
        result = hf_publish.complete(
            slug, job_id,
            version=version,
            external_uri=body.get("external_uri"),
            launched_by=body.get("launched_by"),
            validation_summary=body.get("validation_summary"),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("hf-publish-complete webhook for %s failed: %s", slug, exc)
        return jsonify({"error": str(exc)}), 502
    return jsonify({"ok": True, **result})


@webhooks_bp.route("/release-cut-complete", methods=["POST"])
def release_cut_complete():
    """Record a successful global GH release cut. Idempotent on (version).

    Body: ``{"job_id", "status", "version", "external_uri", "operator_note",
    "launched_by", "members": [...], "validation_summary"}``. Only acts on a
    success status. ``members`` carries the per-recitation membership rows
    the job produced.
    """
    ok, err = _check_secret()
    if not ok:
        return err
    body = request.get_json(silent=True) or {}
    job_id = (body.get("job_id") or "").strip()
    status = (body.get("status") or "").strip().lower()
    version = (body.get("version") or "").strip()
    if not job_id:
        return jsonify({"error": "job_id is required"}), 400
    if status not in _SUCCESS:
        # A failed/aborted cut posts here for observability only — there's
        # nothing to record (only successful cuts insert rows) and the version
        # may be absent (e.g. aborted before it was computed). Don't 400.
        return jsonify({"ok": True, "skipped": "non-success status"})
    if not version:
        return jsonify({"error": "version is required"}), 400
    try:
        result = cut_release.complete(
            None, job_id,
            version=version,
            external_uri=body.get("external_uri"),
            operator_note=body.get("operator_note"),
            launched_by=body.get("launched_by"),
            members=body.get("members") or [],
            validation_summary=body.get("validation_summary"),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("release-cut-complete webhook (v=%s) failed: %s", version, exc)
        return jsonify({"error": str(exc)}), 502
    return jsonify({"ok": True, **result})
