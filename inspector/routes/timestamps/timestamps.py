"""Timestamps tab routes (/api/ts/*).

``/manifest`` and ``/shard/<reciter>/<int:chapter>`` read from
``<INSPECTOR_BUCKET_MOUNT>/reciters/<slug>/timestamps/...`` (composed in
``services/timestamps.py``). ``/config`` advertises manifest + shard URL
templates so the frontend doesn't need its own env knob.
"""

from flask import Blueprint, Response, jsonify

from config import (
    ANALYSIS_LETTER_FONT_SIZE,
    ANALYSIS_WORD_FONT_SIZE,
    ANIM_CHAR_TRANSITION_DURATION,
    ANIM_FONT_SIZE,
    ANIM_HIGHLIGHT_COLOR,
    ANIM_LINE_HEIGHT,
    ANIM_TRANSITION_EASING,
    ANIM_WORD_SPACING,
    ANIM_WORD_TRANSITION_DURATION,
    UNIFIED_DISPLAY_MAX_HEIGHT,
)
from qua_shared.schemas import ErrorEnvelope, TsConfigResponse, TsVbrResponse
from services import auth as auth_service
from services import timestamps as ts_serve
from services.audio_meta import vbr_chapters_for_reciter
from services.auth import capabilities as _capabilities
from utils.decorators import require_capability
from utils.json_response import orjson_response

ts_bp = Blueprint("ts", __name__, url_prefix="/api/ts")


@ts_bp.route("/config")
def ts_config():
    """Return display configuration + read-path URLs for Timestamps tab."""
    config = TsConfigResponse(
        manifest_url="/api/ts/manifest",
        shard_url_template="/api/ts/shard/{reciter}/{chapter}",
        # D20 Track B: reciter dropdown migrates off ``manifest.json.gz`` to the
        # v2 catalog served by the Inspector backend. Frontend prefers this
        # when present; ``manifest_url`` stays as the fallback feeding
        # ts_chapters / vbr_chapters / validation / resources.
        catalog_url="/api/static/catalog.json",
        unified_display_max_height=UNIFIED_DISPLAY_MAX_HEIGHT,
        anim_highlight_color=ANIM_HIGHLIGHT_COLOR,
        anim_word_transition_duration=ANIM_WORD_TRANSITION_DURATION,
        anim_char_transition_duration=ANIM_CHAR_TRANSITION_DURATION,
        anim_transition_easing=ANIM_TRANSITION_EASING,
        anim_word_spacing=ANIM_WORD_SPACING,
        anim_line_height=ANIM_LINE_HEIGHT,
        anim_font_size=ANIM_FONT_SIZE,
        analysis_word_font_size=ANALYSIS_WORD_FONT_SIZE,
        analysis_letter_font_size=ANALYSIS_LETTER_FONT_SIZE,
    )
    return orjson_response(
        config.model_dump(mode="json", exclude_none=True, by_alias=True),
        # Pure constants; changing them needs a server restart.
        headers={"Cache-Control": "public, max-age=300"},
    )


# Shards are precompressed with deterministic Brotli and served with the HTTP
# content encoding so the browser decodes before JSON parsing. A shard mutates
# in place at a stable URL (re-stamp / edit) and the FE already
# holds the active chapter in an in-memory LRU (`ts-source._shards`), so verse
# changes never refetch — the browser HTTP cache only adds staleness with no
# benefit for a body this small. `no-store`: never cached, always fresh on a
# real fetch (chapter switch / reload).
_NO_STORE_HEADERS = {"Cache-Control": "no-store"}
_SHARD_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Encoding": "br",
    "Vary": "Accept-Encoding",
}

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
    """Serve a per-chapter Brotli compact v12 shard (byte pass-through)."""
    # Owner preview: holders of ``timestamps.view_unreleased`` may read shards
    # for generated-but-unreleased reciters; everyone else stays released-only.
    allow_unreleased = _capabilities.can(auth_service.current_user(), "timestamps.view_unreleased")
    body = ts_serve.shard_bytes(reciter, chapter, allow_unreleased=allow_unreleased)
    if body is None:
        return jsonify(ErrorEnvelope(error="Shard not found").model_dump(exclude_none=True)), 404
    return Response(body, mimetype="application/json", headers=_SHARD_HEADERS)


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
        return jsonify(ErrorEnvelope(error="Not found").model_dump(exclude_none=True)), 404
    return orjson_response(doc)


@ts_bp.route("/resource/<name>")
def ts_resource(name):
    """Serve gzipped reference data referenced by the manifest's `resources` block."""
    body = ts_serve.resource_bytes(name)
    if body is None:
        return jsonify(ErrorEnvelope(error="Resource not found").model_dump(exclude_none=True)), 404
    return Response(body, mimetype="application/octet-stream", headers=_NO_STORE_HEADERS)


@ts_bp.route("/vbr/<reciter>")
def ts_vbr(reciter):
    """Return VBR chapters for timestamp clients reading older HF manifests."""
    vbr = TsVbrResponse(vbr_chapters=vbr_chapters_for_reciter(reciter))
    return jsonify(vbr.model_dump(mode="json", exclude_none=True, by_alias=True))
