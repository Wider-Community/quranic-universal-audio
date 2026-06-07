"""Admin Releases-tab endpoints (v2 dataset/release tracks).

- ``POST /api/admin/publish-hf/<slug>``     launch the HF dataset publish job
                                            for ``slug``. Cap-gated by
                                            ``release.publish_hf``.
- ``GET  /api/admin/release-preview``       compute the dry-run diff +
                                            CHANGELOG preview for the cut
                                            modal. No DB writes, no tier
                                            builds. ``release.cut_gh``.
- ``POST /api/admin/cut-release``           launch the global cut job. Owner
                                            (or maintainer with override) via
                                            ``release.cut_gh``. Body carries
                                            optional ``version`` and the
                                            ``expected_version_at_preview``
                                            re-confirm token.
- ``GET  /api/admin/releases/status``       compact per-slug release status
                                            grid for the FE (TS / HF / GH
                                            badges per recitation).

All routes require ``@require_same_origin`` on mutations + a single
capability gate via ``@require_capability``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from qua_shared.schemas import (
    AdminCutReleaseRequest,
    AdminLaunchResponse,
    AdminPublishBatchRequest,
    AdminReleasesStatusResponse,
)
from routes._admin_helpers import require_capability_or_403
from services.admin.jobs import base as jobs_base
from services.admin.jobs import cut_release as cut_release_jobs
from services.admin.jobs import hf_publish as hf_publish_jobs
from services.admin.jobs import hf_publish_batch as hf_publish_batch_jobs
from services.admin.release_preview import build_release_preview, current_auto_version
from services.db import get_conn, repo_releases
from services.state import state as state_service
from utils.decorators import require_capability, require_same_origin

# Per-kind capability gates for the generic release-job cancel route.
_CANCEL_CAPS = {
    "hf_publish": "release.publish_hf",
    "hf_publish_batch": "release.publish_hf",
    "cut_release": "release.cut_gh",
    "timestamps": "reviews.generate_timestamps",
}

log = logging.getLogger("inspector")

admin_releases_bp = Blueprint("admin_releases", __name__, url_prefix="/api/admin")


# ---------------------------------------------------------------------------
# POST /api/admin/publish-hf/<slug>
# ---------------------------------------------------------------------------


@admin_releases_bp.route("/publish-hf/<slug>", methods=["POST"])
@require_same_origin
@require_capability("release.publish_hf")
def publish_hf(user, slug: str):
    """Launch an HF dataset publish job for ``slug``.

    Pre-flight:
      - the slug must exist
      - it must have a current ``per_recitation_releases(track='ts')`` row
        (you can't publish what hasn't been timestamped)
      - no other job for this slug may be in flight (cross-kind single-flight)

    Returns 202 ``{job_id, url}`` on launch, 404 / 409 / 502 on the obvious
    failure modes. The launched job will POST the completion webhook on
    success; the 120 s poll worker is the safety net.
    """
    if state_service.get_row(slug) is None:
        return jsonify({"error": "unknown slug"}), 404
    ts_row = repo_releases.current_release("ts", slug)
    if ts_row is None:
        return jsonify(
            {
                "error": "this recitation has no current TS release — "
                "generate timestamps before publishing to HF",
            }
        ), 409
    # Cross-kind single-flight on the slug.
    busy = jobs_base.running_job_for(slug=slug)
    if busy is not None:
        return jsonify(
            {"error": "a job is already running for this slug", "kind": busy[0], "job_id": busy[1]}
        ), 409
    # Global single-flight against an in-flight cut_release: a publish landing
    # mid-cut would risk a per_recitation_releases(track='hf') row whose
    # timestamps are about to be frozen into a new gh_release — wait for the
    # cut to complete before publishing.
    cut_busy = jobs_base.running_job_for(kind="cut_release")
    if cut_busy is not None:
        return jsonify(
            {
                "error": "a cut_release is in flight — wait for it to finish",
                "kind": cut_busy[0],
                "job_id": cut_busy[1],
            }
        ), 409
    # A batch publish may be processing this slug (or about to) — don't race it.
    batch_busy = jobs_base.running_job_for(kind="hf_publish_batch")
    if batch_busy is not None:
        return jsonify(
            {
                "error": "a batch publish is in flight — wait for it to finish",
                "kind": batch_busy[0],
                "job_id": batch_busy[1],
            }
        ), 409
    webhook_base = request.url_root
    try:
        result = hf_publish_jobs.launch(slug, webhook_base=webhook_base)
    except Exception as exc:  # surfaced to the drawer
        log.warning("publish-hf launch for %s failed: %s", slug, exc)
        return jsonify({"error": str(exc)}), 502
    out = AdminLaunchResponse.model_validate(result)
    return jsonify(out.model_dump(mode="json")), 202


# ---------------------------------------------------------------------------
# POST /api/admin/publish-hf-batch
# ---------------------------------------------------------------------------


@admin_releases_bp.route("/publish-hf-batch", methods=["POST"])
@require_same_origin
@require_capability("release.publish_hf")
def publish_hf_batch(user):
    """Launch ONE HF Job that publishes a batch of recitations.

    Body: ``{"slugs": [str, ...]}``. Pre-flight: every slug must exist and have
    a current ``ts`` release row; none may have a job already in flight; no
    ``cut_release`` and no other ``hf_publish_batch`` may be running. The job
    publishes each split independently (one slug failing never aborts the
    batch) and reports per-slug results via the completion webhook.

    Returns 202 ``{job_id, url}``.
    """
    try:
        req = AdminPublishBatchRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid batch request", "details": exc.errors()}), 400

    # De-dup while preserving order.
    slugs = list(dict.fromkeys(s.strip() for s in req.slugs if s.strip()))
    if not slugs:
        return jsonify({"error": "no slugs provided"}), 400

    if jobs_base.running_job_for(kind="cut_release") is not None:
        return jsonify({"error": "a cut_release is in flight — wait for it to finish"}), 409
    if jobs_base.running_job_for(kind="hf_publish_batch") is not None:
        return jsonify({"error": "a batch publish is already running"}), 409

    for slug in slugs:
        if state_service.get_row(slug) is None:
            return jsonify({"error": f"unknown slug: {slug}"}), 404
        if repo_releases.current_release("ts", slug) is None:
            return jsonify(
                {"error": f"{slug} has no current TS release — generate timestamps first"}
            ), 409
        busy = jobs_base.running_job_for(slug=slug)
        if busy is not None:
            return jsonify(
                {
                    "error": f"a job is already running for {slug}",
                    "kind": busy[0],
                    "job_id": busy[1],
                }
            ), 409

    webhook_base = request.url_root
    try:
        result = hf_publish_batch_jobs.launch(slugs, webhook_base=webhook_base)
    except Exception as exc:
        log.warning("publish-hf-batch launch failed: %s", exc)
        return jsonify({"error": str(exc)}), 502
    out = AdminLaunchResponse.model_validate(result)
    return jsonify(out.model_dump(mode="json")), 202


# ---------------------------------------------------------------------------
# POST /api/admin/release-jobs/<job_id>/cancel
# ---------------------------------------------------------------------------


@admin_releases_bp.route("/release-jobs/<job_id>/cancel", methods=["POST"])
@require_same_origin
@require_capability("reviews.view")
def cancel_release_job(user, job_id):
    """Cancel an in-flight release job (publish / batch / cut / timestamps).

    Outer gate is ``reviews.view`` (anyone who sees the Releases tab); the
    actual cancel is then gated per-kind against the same capability that
    launched it (publish/batch → ``release.publish_hf``, cut → ``release.cut_gh``,
    timestamps → ``reviews.generate_timestamps``). Returns
    ``{job_id, canceled}``; 404 if the job isn't found, 502 on HF error."""
    from huggingface_hub import cancel_job as hf_cancel_job

    kind = jobs_base.kind_for_job(job_id)
    if kind is None:
        return jsonify({"error": "job not found"}), 404
    cap = _CANCEL_CAPS.get(kind)
    if cap is not None:
        denied = require_capability_or_403(user, cap)
        if denied is not None:
            return denied
    try:
        hf_cancel_job(job_id)
    except Exception as exc:
        log.warning("cancel release job %s (%s) failed: %s", job_id, kind, exc)
        return jsonify({"error": str(exc)}), 502
    from services.storage import cache as _cache

    _cache.invalidate_in_flight_jobs_cache()
    return jsonify({"job_id": job_id, "canceled": True})


# ---------------------------------------------------------------------------
# GET /api/admin/release-preview
# ---------------------------------------------------------------------------


@admin_releases_bp.route("/release-preview", methods=["GET"])
@require_capability("release.cut_gh")
def release_preview(user):
    """Dry-run preview for the cut-release modal.

    Reads ``per_recitation_releases`` (track='ts', current rows, GH-eligible
    channels) + the most-recent ``gh_release_recitations`` to compute change
    counts (added / refresh / unchanged), the auto-computed next version, and
    a rendered CHANGELOG.md preview. No tier-file builds — runs on a single
    DB query. Use the returned ``expected_version_at_preview`` token as the
    confirm-step idempotency check.
    """
    out = build_release_preview()
    return jsonify(out.model_dump(mode="json"))


def _current_auto_version() -> tuple[str | None, int]:
    return current_auto_version()


# ---------------------------------------------------------------------------
# POST /api/admin/cut-release
# ---------------------------------------------------------------------------


@admin_releases_bp.route("/cut-release", methods=["POST"])
@require_same_origin
@require_capability("release.cut_gh")
def cut_release(user):
    """Launch a global GH release cut.

    Body:
      - ``version``: vX.Y.Z manual override (required when preview says
        ``needs_manual_version``)
      - ``expected_version_at_preview``: the version the preview computed —
        rejected (409) if it doesn't match the current auto-compute, so the
        operator re-previews stale state.

    Global single-flight: rejects (409) if another cut is in flight.
    """
    if jobs_base.running_job_for(kind="cut_release") is not None:
        return jsonify({"error": "a cut_release job is already running"}), 409
    if jobs_base.running_job_for(kind="hf_publish_batch") is not None:
        return jsonify(
            {"error": "a batch publish is in flight — wait for it to finish before cutting"}
        ), 409
    try:
        cut_request = AdminCutReleaseRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid cut-release request", "details": exc.errors()}), 400

    version = (cut_request.version or "").strip() or None
    expected = (cut_request.expected_version_at_preview or "").strip() or None

    # Drift check: re-run the cheap preview compute and compare. A manual
    # version override may accompany ``expected=None`` when the preview said
    # "nothing changed"; that is stable as long as the current auto-version is
    # still None.
    if expected is not None:
        current_auto_version, candidates_count = _current_auto_version()
        if candidates_count == 0:
            return jsonify({"error": "no eligible recitations"}), 409
        if current_auto_version != expected:
            return jsonify(
                {
                    "error": "release preview drifted; refresh the preview before cutting",
                    "expected_version_at_preview": expected,
                    "current_computed_version": current_auto_version,
                }
            ), 409

    webhook_base = request.url_root
    try:
        result = cut_release_jobs.launch(
            version=version,
            launched_by=getattr(user, "hf_user_id", None),
            webhook_base=webhook_base,
        )
    except Exception as exc:
        log.warning("cut-release launch failed: %s", exc)
        return jsonify({"error": str(exc)}), 502
    out = AdminLaunchResponse.model_validate(result)
    return jsonify(out.model_dump(mode="json")), 202


# ---------------------------------------------------------------------------
# GET /api/admin/releases/status
# ---------------------------------------------------------------------------


@admin_releases_bp.route("/releases/status", methods=["GET"])
@require_capability("reviews.view")
def releases_status(user):
    """Per-recitation release status + summary + in-flight jobs for the FE.

    Returns:
      {
        "latest_gh_release": {version, produced_at, external_uri} | null,
        "summary": {                          # latest cut + aggregate metrics
          "version", "produced_at", "external_uri",
          "member_count", "total_bytes", "days_since_cut"
        } | null,
        "in_flight": [                        # live HF Jobs (5 s TTL cache)
          {"kind", "slug" | null, "job_id", "started_at"}, ...
        ],
        "recitations": [{
          slug, name_en, name_ar, state,
          riwayah, style, channel,
          gh_release_eligible: bool,
          ts: {version, produced_at} | null,
          hf: {version, produced_at, stale_since} | null,
          gh: {change_kind, stale_since, release_id, ts_version} | null,
        }, ...]
      }

    Only rows the FE compartment will place in a visible bucket are
    returned (see ``_is_bucketable``) — inert catalog entries are dropped
    server-side so chip facet counts reflect actual release activity.

    Gated by ``reviews.view`` (any admin who sees the review queue sees this
    grid; the action gates above own who can mutate). FE buckets rows into
    state sections; ``state`` (released / under_review / awaiting_review)
    drives the "Waiting to publish" predicate, ``in_flight`` drives the
    "In progress" predicate.
    """
    conn = get_conn()
    latest_gh = repo_releases.latest_gh_release()

    # Aggregated summary row for the top card. None when no release cut yet.
    summary_row = repo_releases.latest_gh_release_summary()
    summary: dict | None = None
    if summary_row is not None:
        produced_at = summary_row.get("produced_at")
        days_since_cut: int | None = None
        if produced_at:
            try:
                # produced_at is ISO-8601 UTC ("YYYY-MM-DDTHH:MM:SSZ"); replace
                # Z so fromisoformat handles it on Python < 3.11.
                dt = datetime.fromisoformat(produced_at.replace("Z", "+00:00"))
                days_since_cut = max(0, (datetime.now(UTC) - dt).days)
            except Exception:
                days_since_cut = None
        summary = {
            "version": summary_row.get("version"),
            "produced_at": produced_at,
            "external_uri": summary_row.get("external_uri"),
            "member_count": int(summary_row.get("member_count") or 0),
            "total_bytes": int(summary_row.get("total_bytes") or 0),
            "days_since_cut": days_since_cut,
        }

    # ``timestamps`` is watched too: a running first-publish OR regen MFA job
    # surfaces in the "In progress" bucket (a regen on a released row has no
    # other in-flight signal — there's no state change). hf_publish + cut_release
    # are the dataset/GH tracks.
    in_flight = jobs_base.list_in_flight_jobs(
        ("hf_publish", "hf_publish_batch", "cut_release", "timestamps")
    )

    # Most-recent batch publish outcome — drives the "Failed to publish" bucket
    # (per-row ``publish_error``) and the dismissable summary banner
    # (``last_batch``). A failed member clears once a later HF release for that
    # slug supersedes it (the operator retried successfully).
    batch_outcome = hf_publish_batch_jobs.latest_batch_outcome()
    batch_failures: dict[str, dict] = {}
    last_batch: dict | None = None
    if batch_outcome is not None:
        members = batch_outcome.get("members") or []
        completed_at = batch_outcome.get("completed_at")
        batch_job_id = batch_outcome.get("job_id") or ""
        published_count = sum(1 for m in members if m.get("status") == "succeeded")
        failed_count = 0
        for m in members:
            if m.get("status") == "succeeded":
                continue
            slug = (m.get("slug") or "").strip()
            if not slug:
                continue
            # Cleared if a current HF release landed at/after this batch.
            hf_row = repo_releases.current_release("hf", slug)
            if (
                hf_row is not None
                and completed_at
                and (hf_row.get("produced_at") or "") >= completed_at
            ):
                continue
            batch_failures[slug] = {
                "message": m.get("error") or "publish failed",
                "job_id": batch_job_id,
                "at": completed_at,
            }
            failed_count += 1
        if failed_count > 0:
            last_batch = {
                "job_id": batch_job_id,
                "at": completed_at,
                "published_count": published_count,
                "failed_count": failed_count,
            }

    deliveries = conn.execute("""
        SELECT d.slug, d.riwayah, d.style, d.channel,
               r.name_en, r.name_ar,
               ds.state
        FROM deliveries d
        JOIN reciters        r  ON r.reciter_id = d.reciter_id
        LEFT JOIN delivery_states ds ON ds.slug = d.slug
        ORDER BY d.slug
    """).fetchall()

    in_flight_slugs = {j["slug"] for j in in_flight if j.get("slug")}

    out: list[dict] = []
    for d in deliveries:
        slug = d["slug"]
        ts = repo_releases.current_release("ts", slug)
        hf = repo_releases.current_release("hf", slug)
        gh = repo_releases.latest_gh_release_member(slug)
        row = {
            "slug": slug,
            "name_en": d["name_en"],
            "name_ar": d["name_ar"],
            "state": d["state"],
            "riwayah": d["riwayah"],
            "style": d["style"],
            "channel": d["channel"],
            "ts": _slim_release_row(ts, fields=("version", "produced_at")),
            "hf": _slim_release_row(hf, fields=("version", "produced_at", "stale_since")),
            "gh": _slim_release_row(
                gh, fields=("change_kind", "stale_since", "release_id", "ts_version")
            ),
            "publish_error": batch_failures.get(slug),
        }
        if _is_bucketable(row, in_flight_slugs) or slug in batch_failures:
            out.append(row)
    payload = AdminReleasesStatusResponse.model_validate(
        {
            "latest_gh_release": _slim_release_row(
                latest_gh,
                fields=("version", "produced_at", "external_uri"),
            ),
            "summary": summary,
            "in_flight": in_flight,
            "recitations": out,
            "last_batch": last_batch,
        }
    )
    return jsonify(payload.model_dump(mode="json"))


def _is_bucketable(row: dict, in_flight_slugs: set[str]) -> bool:
    """True iff the FE compartment will assign ``row`` to a visible bucket.

    Mirrors ``bucketOf()`` in ``ReleasesCompartment.svelte``. Filters out
    inert catalog rows (no TS, no HF, no GH membership, not released) so
    the FE never sees facet chips counting reciters that have no release
    activity. Priority-first like the FE — any single match returns True.
    """
    if row["slug"] in in_flight_slugs:
        return True
    if row["hf"] is not None:
        return True
    if row["gh"] is not None:
        return True
    if row["state"] == "released" and row["ts"] is not None:
        return True
    return False


def _slim_release_row(row: dict | None, *, fields: tuple[str, ...]) -> dict | None:
    if row is None:
        return None
    return {k: row.get(k) for k in fields if k in row}
