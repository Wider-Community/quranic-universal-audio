"""Timestamps tab routes (/api/ts/*).

``/manifest`` and ``/shard/<reciter>/<int:chapter>`` read from
``<INSPECTOR_BUCKET_MOUNT>/reciters/<slug>/timestamps/...`` (composed in
``services/timestamps.py``). ``/config`` advertises manifest + shard URL
templates so the frontend doesn't need its own env knob.
"""
from flask import Blueprint, Response, jsonify, request

from config import (
    UNIFIED_DISPLAY_MAX_HEIGHT,
    ANIM_HIGHLIGHT_COLOR, ANIM_WORD_TRANSITION_DURATION,
    ANIM_CHAR_TRANSITION_DURATION, ANIM_TRANSITION_EASING,
    ANIM_WORD_SPACING, ANIM_LINE_HEIGHT, ANIM_FONT_SIZE,
    ANALYSIS_WORD_FONT_SIZE, ANALYSIS_LETTER_FONT_SIZE,
)
from services.audio_meta import vbr_chapters_for_reciter
from services import auth as auth_service
from services import tajweed as ts_tajweed
from services import timestamps as ts_serve
from services.auth import capabilities as _capabilities
from utils.decorators import require_capability
from utils.json_response import orjson_response

ts_bp = Blueprint("ts", __name__, url_prefix="/api/ts")


@ts_bp.route("/config")
def ts_config():
    """Return display configuration + read-path URLs for Timestamps tab."""
    return orjson_response(
        {
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
        },
        # Pure constants; changing them needs a server restart.
        headers={"Cache-Control": "public, max-age=300"},
    )


# Bodies are pre-gzipped (`mtime=0`, deterministic). Sent without a
# `Content-Encoding: gzip` header — the frontend decompresses with
# `DecompressionStream('gzip')` so the same code path handles bucket + local.
# Shards are immutable per published reciter, so they keep the long cache.
_GZIP_HEADERS = {"Cache-Control": "public, max-age=86400"}

# The manifest changes whenever a reciter is published/unpublished. The server
# rebuilds it on the next request after any lifecycle transition (state.py
# invalidates the process cache), so a short client TTL is what bounds how long
# a stale published-set lingers in the browser. 10 min trades a tiny re-fetch
# (a few hundred gzipped bytes) for prompt propagation of publish changes.
_MANIFEST_HEADERS = {"Cache-Control": "public, max-age=600"}


@ts_bp.route("/manifest")
def ts_manifest():
    """Serve the pre-built gzipped manifest (local or bucket source)."""
    return Response(
        ts_serve.manifest_bytes(),
        mimetype="application/octet-stream",
        headers=_MANIFEST_HEADERS,
    )


@ts_bp.route("/shard/<reciter>/<int:chapter>")
def ts_shard(reciter, chapter):
    """Serve a per-chapter gzipped segment-array shard (byte pass-through)."""
    # Owner preview: holders of ``timestamps.view_unreleased`` may read shards
    # for generated-but-unreleased reciters; everyone else stays released-only.
    allow_unreleased = _capabilities.can(
        auth_service.current_user(), "timestamps.view_unreleased"
    )
    body = ts_serve.shard_bytes(reciter, chapter, allow_unreleased=allow_unreleased)
    if body is None:
        return jsonify({"error": "Shard not found"}), 404
    return Response(body, mimetype="application/octet-stream", headers=_GZIP_HEADERS)


@ts_bp.route("/validation/<reciter>")
@require_capability("timestamps.view_validation")
def ts_validation(user, reciter):
    """Verse-level ts-validation flags for the Timestamps-tab accordion.

    Gated on ``timestamps.view_validation`` (owner + maintainer by default;
    hidden to contributors/anon). Within that, the unreleased-reciter bypass
    reuses ``timestamps.view_unreleased`` — a maintainer therefore sees flags
    for released recitations only, while an owner sees everything.

    Returns ``{"_meta", "verses"}`` from the reciter's ``ts_validation.json`` —
    an empty doc when the reciter is viewable but never ran with probe beams,
    so the FE shows an empty panel. Non-viewable reciters get 404 (no leak of
    unreleased existence).
    """
    allow_unreleased = _capabilities.can(user, "timestamps.view_unreleased")
    doc = ts_serve.ts_validation_doc(reciter, allow_unreleased=allow_unreleased)
    if doc is None:
        return jsonify({"error": "Not found"}), 404
    return orjson_response(doc)


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


# Cross-word tajweed bridges (rules that span a word boundary). Reciter-agnostic
# given the stop set, so we don't take a reciter in the URL — the FE infers
# stops from MFA word-end gaps in the loaded shard and forwards them as the
# ``stops`` query string. The service is lru_cached so concurrent reciters with
# matching stop patterns share the result.
_TAJWEED_HEADERS = {"Cache-Control": "public, max-age=86400"}


@ts_bp.route("/tajweed/<path:verse_ref>")
def ts_tajweed_bridges(verse_ref):
    """Return cross-word tajweed bridges for ``verse_ref`` under inferred stops.

    Query parameters
    ----------------
    ``stops``
        Comma-separated ``surah:ayah:word`` stop refs (one per reciter pause)
        — passed through to the phonemizer's ``stop_refs``. Empty / missing
        means the verse is read continuously.

    Response
    --------
    ``{"verse_ref", "stops", "bridges": [BridgeInfo, ...]}`` matching
    :class:`qua_shared.schemas.tajweed.TajweedBridgesResponse`.
    """
    raw_stops = request.args.get("stops", "")
    stops = tuple(s for s in raw_stops.split(",") if s) if raw_stops else ()
    bridges = ts_tajweed.bridges_for_verse(verse_ref, stops)
    return orjson_response(
        {
            "verse_ref": verse_ref,
            "stops": list(stops),
            "bridges": [b.model_dump() for b in bridges],
        },
        headers=_TAJWEED_HEADERS,
    )
