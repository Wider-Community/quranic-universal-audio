"""Timestamps tab routes (/api/ts/*).

Two read paths share the same shard-fetch model on the frontend:
  - **local**  mode: this blueprint's `/manifest`, `/shard/<reciter>/<int:chapter>`,
    and `/resource/<name>` endpoints serve gzipped bodies sliced from the
    on-disk timestamps tree (`services/timestamps.py` local branch).
  - **bucket** mode: same URL surface, but `/manifest` and `/shard` read from
    `<INSPECTOR_BUCKET_MOUNT>/published/<slug>/timestamps/...` (composed in
    the `services/timestamps.py` bucket branch).

`/config` advertises the active mode + manifest/shard URL templates so the
frontend can pick the right base without needing its own env knob.
"""
import os

from flask import Blueprint, Response, jsonify

from config import (
    UNIFIED_DISPLAY_MAX_HEIGHT,
    ANIM_HIGHLIGHT_COLOR, ANIM_WORD_TRANSITION_DURATION,
    ANIM_CHAR_TRANSITION_DURATION, ANIM_TRANSITION_EASING,
    ANIM_WORD_SPACING, ANIM_LINE_HEIGHT, ANIM_FONT_SIZE,
    ANALYSIS_WORD_FONT_SIZE, ANALYSIS_LETTER_FONT_SIZE,
    TS_SOURCE,
)
from services.audio_meta import vbr_chapters_for_reciter
from services import timestamps as ts_serve
from services.validation import validate_reciter_timestamps

ts_bp = Blueprint("ts", __name__, url_prefix="/api/ts")


@ts_bp.route("/config")
def ts_config():
    """Return display configuration + read-path URLs for Timestamps tab.

    `mode`, `manifest_url`, and `shard_url_template` drive the frontend's
    shard-fetch model. URLs are identical in local and bucket modes — only
    the backend's data source differs.
    """
    return jsonify({
        "mode": TS_SOURCE,
        "manifest_url": "/api/ts/manifest",
        "shard_url_template": "/api/ts/shard/{reciter}/{chapter}",
        # D20 Track B: reciter dropdown migrates off ``manifest.json.gz`` to the
        # v2 catalog served by the Inspector backend. Frontend prefers this
        # when present; ``manifest_url`` stays as the fallback feeding
        # ts_chapters / vbr_chapters / validation / resources.
        "catalog_url": "/api/static/catalog.json",
        "unified_display_max_height": UNIFIED_DISPLAY_MAX_HEIGHT,
        "anim_highlight_color": ANIM_HIGHLIGHT_COLOR,
        "anim_word_transition_duration": ANIM_WORD_TRANSITION_DURATION,
        "anim_char_transition_duration": ANIM_CHAR_TRANSITION_DURATION,
        "anim_transition_easing": ANIM_TRANSITION_EASING,
        "anim_word_spacing": ANIM_WORD_SPACING,
        "anim_line_height": ANIM_LINE_HEIGHT,
        "anim_font_size": ANIM_FONT_SIZE,
        "analysis_word_font_size": ANALYSIS_WORD_FONT_SIZE,
        "analysis_letter_font_size": ANALYSIS_LETTER_FONT_SIZE,
    })


# Bodies are pre-gzipped (`mtime=0`, deterministic). Sent without a
# `Content-Encoding: gzip` header — the frontend decompresses with
# `DecompressionStream('gzip')` so the same code path handles bucket + local.
# Manifest/shard mutate when reciters are published; 1-day cache keeps perf
# good while bounding staleness to a publish-cycle window.
_GZIP_HEADERS = {"Cache-Control": "public, max-age=86400"}


@ts_bp.route("/manifest")
def ts_manifest():
    """Serve the pre-built gzipped manifest (local or bucket source)."""
    return Response(
        ts_serve.manifest_bytes(),
        mimetype="application/octet-stream",
        headers=_GZIP_HEADERS,
    )


@ts_bp.route("/shard/<reciter>/<int:chapter>")
def ts_shard(reciter, chapter):
    """Serve a per-chapter gzipped shard (local or bucket source)."""
    body = ts_serve.shard_bytes(reciter, chapter)
    if body is None:
        return jsonify({"error": "Shard not found"}), 404
    return Response(body, mimetype="application/octet-stream", headers=_GZIP_HEADERS)


@ts_bp.route("/resource/<name>")
def ts_resource(name):
    """Serve gzipped reference data referenced by the manifest's `resources` block."""
    body = ts_serve.resource_bytes(name)
    if body is None:
        return jsonify({"error": "Resource not found"}), 404
    return Response(body, mimetype="application/octet-stream", headers=_GZIP_HEADERS)


@ts_bp.route("/vbr/<reciter>")
def ts_vbr(reciter):
    """Return VBR chapters for timestamp clients reading older HF manifests."""
    return jsonify({"vbr_chapters": vbr_chapters_for_reciter(reciter)})


@ts_bp.route("/validate/<reciter>")
def ts_validate(reciter):
    """Validate timestamp data via the in-process timestamps validator.

    Gated behind ``INSPECTOR_TS_VALIDATE_ENABLED`` (default ``1`` for local).
    Deployed Spaces flip it to ``0``; the validator reads from the on-disk
    timestamps tree which doesn't exist in the bucket layout.
    """
    if os.environ.get("INSPECTOR_TS_VALIDATE_ENABLED", "1") != "1":
        return jsonify({
            "error": "ts_validate is disabled in deployed mode "
                     "(see INSPECTOR_TS_VALIDATE_ENABLED)"
        }), 410

    result = validate_reciter_timestamps(reciter)
    if result is None:
        return jsonify({"error": "Reciter not found"}), 404
    return jsonify(result)
