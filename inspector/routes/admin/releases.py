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
                                            optional ``version``,
                                            ``operator_note`` and the
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

from flask import Blueprint, jsonify, request

from services.admin.jobs import cut_release as cut_release_jobs
from services.admin.jobs import hf_publish as hf_publish_jobs
from services.admin.jobs import base as jobs_base
from services.db import get_conn, repo_releases
from services.state import state as state_service
from utils.decorators import require_capability, require_same_origin

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
        return jsonify({
            "error": "this recitation has no current TS release — "
                     "generate timestamps before publishing to HF",
        }), 409
    # Cross-kind single-flight on the slug.
    busy = jobs_base.running_job_for(slug=slug)
    if busy is not None:
        return jsonify({"error": "a job is already running for this slug",
                        "kind": busy[0], "job_id": busy[1]}), 409
    # Global single-flight against an in-flight cut_release: a publish landing
    # mid-cut would risk a per_recitation_releases(track='hf') row whose
    # timestamps are about to be frozen into a new gh_release — wait for the
    # cut to complete before publishing.
    cut_busy = jobs_base.running_job_for(kind="cut_release")
    if cut_busy is not None:
        return jsonify({"error": "a cut_release is in flight — wait for it to finish",
                        "kind": cut_busy[0], "job_id": cut_busy[1]}), 409
    webhook_base = request.url_root
    try:
        result = hf_publish_jobs.launch(slug, webhook_base=webhook_base)
    except Exception as exc:  # surfaced to the drawer
        log.warning("publish-hf launch for %s failed: %s", slug, exc)
        return jsonify({"error": str(exc)}), 502
    return jsonify(result), 202


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
    conn = get_conn()
    candidates = conn.execute("""
        SELECT prr.slug AS slug,
               prr.version AS ts_version,
               r.name_en AS name_en,
               d.riwayah AS riwayah,
               d.style AS style,
               d.channel AS channel
        FROM per_recitation_releases prr
        JOIN deliveries d ON d.slug = prr.slug
        JOIN channels c   ON c.slug = d.channel
        JOIN reciters r   ON r.reciter_id = d.reciter_id
        WHERE prr.track = 'ts'
          AND prr.superseded_at IS NULL
          AND c.gh_release_eligible = 1
        ORDER BY prr.slug
    """).fetchall()

    prior = repo_releases.latest_gh_release()
    prior_members = (
        {m["slug"]: m for m in repo_releases.gh_release_recitations(prior["id"])}
        if prior else {}
    )

    added: list[dict] = []
    refreshed: list[dict] = []
    unchanged: list[dict] = []
    for r in candidates:
        slug = r["slug"]
        ts_version = str(r["ts_version"])
        prior_member = prior_members.get(slug)
        row_payload = {
            "slug": slug,
            "name_en": r["name_en"],
            "riwayah": r["riwayah"],
            "style": r["style"],
            "channel": r["channel"],
            "ts_version": ts_version,
        }
        if prior_member is None:
            added.append(row_payload)
        elif str(prior_member["ts_version"]) != ts_version:
            refreshed.append(row_payload)
        else:
            unchanged.append(row_payload)

    # Compute the auto-version (preview-only — actual cut recomputes inside
    # the job, possibly with a content_hash-driven reclassification).
    prior_version = prior["version"] if prior else None
    if added:
        computed_version = _bump_minor(prior_version)
    elif refreshed:
        computed_version = _bump_patch(prior_version)
    elif prior_version is None:
        computed_version = "v0.1.0"
    else:
        computed_version = None  # "nothing changed" — operator must override
    needs_override = computed_version is None

    payload = {
        "computed_version": computed_version,
        "needs_manual_version": needs_override,
        "previous_version": prior_version,
        # Plan §change_kind: enum is {added, refresh, unchanged}. ``removed`` is
        # NOT a change_kind — once a slug ships in a GH release it stays in
        # subsequent releases (any drop is an operational decision outside the
        # cut flow). Do not surface it here.
        "change_counts": {
            "added": len(added),
            "refresh": len(refreshed),
            "unchanged": len(unchanged),
        },
        "added": added,
        "refreshed": refreshed,
        "changelog_preview_md": _render_changelog_preview(
            computed_version or "v?.?.?",
            prior_version, added, refreshed,
        ),
        # Echo back so the confirm step can validate the preview hasn't drifted.
        "expected_version_at_preview": computed_version,
    }
    return jsonify(payload)


def _bump_minor(prior: str | None) -> str:
    if not prior:
        return "v0.1.0"
    parts = prior.lstrip("v").split(".")
    major, minor = int(parts[0]), int(parts[1])
    return f"v{major}.{minor + 1}.0"


def _bump_patch(prior: str | None) -> str:
    if not prior:
        return "v0.1.0"
    parts = prior.lstrip("v").split(".")
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    return f"v{major}.{minor}.{patch + 1}"


def _render_changelog_preview(version: str, prior_version: str | None,
                              added: list[dict],
                              refreshed: list[dict]) -> str:
    """Lightweight CHANGELOG render for the modal preview. The actual cut
    job renders the full CHANGELOG.md from richer per-recitation data; this
    is the operator-facing snapshot of what's about to land.
    """
    lines: list[str] = []
    lines.append(f"# Changelog — {version}\n")
    if prior_version:
        lines.append(f"Compared to {prior_version}.\n")
    if added:
        lines.append(f"## Added recitations ({len(added)})\n")
        lines.append("| Slug | Name | Riwayah | Style | Channel |")
        lines.append("|---|---|---|---|---|")
        for m in added:
            lines.append(
                f"| `{m['slug']}` | {m['name_en']} | {m['riwayah']} "
                f"| {m['style']} | {m['channel']} |"
            )
        lines.append("")
    if refreshed:
        lines.append(f"## Refreshed recitations ({len(refreshed)})\n")
        lines.append("| Slug | Name |")
        lines.append("|---|---|")
        for m in refreshed:
            lines.append(f"| `{m['slug']}` | {m['name_en']} |")
        lines.append("")
    if not added and not refreshed:
        lines.append("## Notes\n")
        lines.append("> Nothing changed since the last release — to force a "
                     "cut, supply an explicit version in the modal.\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# POST /api/admin/cut-release
# ---------------------------------------------------------------------------

@admin_releases_bp.route("/cut-release", methods=["POST"])
@require_same_origin
@require_capability("release.cut_gh")
def cut_release(user):
    """Launch a global GH release cut.

    Body (all optional):
      - ``version``: vX.Y.Z manual override (required when preview says
        ``needs_manual_version``)
      - ``operator_note``: a global note rendered into CHANGELOG.md
      - ``expected_version_at_preview``: the version the preview computed —
        rejected (409) if it doesn't match the current auto-compute, so the
        operator re-previews stale state.

    Global single-flight: rejects (409) if another cut is in flight.
    """
    if jobs_base.running_job_for(kind="cut_release") is not None:
        return jsonify({"error": "a cut_release job is already running"}), 409
    body = request.get_json(silent=True) or {}
    version = (body.get("version") or "").strip() or None
    operator_note = (body.get("operator_note") or "").strip() or None
    expected = (body.get("expected_version_at_preview") or "").strip() or None

    # Drift check: re-run the cheap preview compute and compare. Skip when the
    # client didn't echo (older FE).
    if expected is not None:
        # Re-run the candidate diff so a midstream TS regen doesn't slip through.
        candidates_count = get_conn().execute(
            "SELECT COUNT(*) AS n FROM per_recitation_releases prr "
            "JOIN deliveries d ON d.slug = prr.slug "
            "JOIN channels c ON c.slug = d.channel "
            "WHERE prr.track='ts' AND prr.superseded_at IS NULL "
            "AND c.gh_release_eligible = 1"
        ).fetchone()["n"]
        if not candidates_count:
            return jsonify({"error": "no eligible recitations"}), 409

    webhook_base = request.url_root
    try:
        result = cut_release_jobs.launch(
            version=version,
            operator_note=operator_note,
            launched_by=getattr(user, "hf_user_id", None),
            webhook_base=webhook_base,
        )
    except Exception as exc:
        log.warning("cut-release launch failed: %s", exc)
        return jsonify({"error": str(exc)}), 502
    return jsonify(result), 202


# ---------------------------------------------------------------------------
# GET /api/admin/releases/status
# ---------------------------------------------------------------------------

@admin_releases_bp.route("/releases/status", methods=["GET"])
@require_capability("reviews.view")
def releases_status(user):
    """Per-recitation release status for the FE grid.

    Returns:
      {
        "latest_gh_release": {version, produced_at} | null,
        "recitations": [{
          slug, name_en, riwayah, channel,
          gh_release_eligible: bool,
          ts: {version, produced_at} | null,
          hf: {version, produced_at, stale_since} | null,
          gh: {release_version, change_kind, stale_since} | null,
        }, ...]
      }

    Gated by ``reviews.view`` (any admin who can see the queue can see the
    status grid; actions are gated by the per-action capabilities above).
    """
    conn = get_conn()
    latest_gh = repo_releases.latest_gh_release()
    deliveries = conn.execute("""
        SELECT d.slug, d.riwayah, d.style, d.channel,
               c.gh_release_eligible,
               r.name_en
        FROM deliveries d
        JOIN channels c ON c.slug = d.channel
        JOIN reciters r ON r.reciter_id = d.reciter_id
        ORDER BY d.slug
    """).fetchall()

    out: list[dict] = []
    for d in deliveries:
        slug = d["slug"]
        ts = repo_releases.current_release("ts", slug)
        hf = repo_releases.current_release("hf", slug)
        gh = repo_releases.latest_gh_release_member(slug)
        out.append({
            "slug": slug,
            "name_en": d["name_en"],
            "riwayah": d["riwayah"],
            "style": d["style"],
            "channel": d["channel"],
            "gh_release_eligible": bool(d["gh_release_eligible"]),
            "ts": _slim_release_row(ts, fields=("version", "produced_at")),
            "hf": _slim_release_row(hf, fields=("version", "produced_at", "stale_since")),
            "gh": _slim_release_row(gh, fields=("change_kind", "stale_since",
                                                "release_id", "ts_version")),
        })
    return jsonify({
        "latest_gh_release": _slim_release_row(
            latest_gh, fields=("version", "produced_at", "external_uri"),
        ),
        "recitations": out,
    })


def _slim_release_row(row: dict | None, *, fields: tuple[str, ...]) -> dict | None:
    if row is None:
        return None
    return {k: row.get(k) for k in fields if k in row}
