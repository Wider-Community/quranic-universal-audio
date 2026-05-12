"""Timestamps tab routes (/api/ts/*).

Two read paths share the same shard-fetch model on the frontend:
  - **local**  mode: this blueprint's `/manifest`, `/shard/<reciter>/<int:chapter>`,
    and `/resource/<name>` endpoints serve gzipped bodies sliced from the
    on-disk timestamps tree (`services/ts_local.py`).
  - **bucket** mode: same URL surface, but `/manifest` and `/shard` read from
    `<INSPECTOR_BUCKET_MOUNT>/published/<slug>/timestamps/...` (composed in
    `services/ts_local.py`'s bucket variant).

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
    SURAH_INFO_PATH,
    TIMESTAMPS_PATH,
    TS_BOUNDARY_TOLERANCE_MS,
    TS_SOURCE,
    MISSING_WORD_DIFF_MS_WEIGHT,
)
from constants import TS_AUDIO_CATEGORIES
from services.audio_meta import vbr_chapters_for_reciter
from services import ts_local

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
        ts_local.manifest_bytes(),
        mimetype="application/octet-stream",
        headers=_GZIP_HEADERS,
    )


@ts_bp.route("/shard/<reciter>/<int:chapter>")
def ts_shard(reciter, chapter):
    """Serve a per-chapter gzipped shard (local or bucket source)."""
    body = ts_local.shard_bytes(reciter, chapter)
    if body is None:
        return jsonify({"error": "Shard not found"}), 404
    return Response(body, mimetype="application/octet-stream", headers=_GZIP_HEADERS)


@ts_bp.route("/resource/<name>")
def ts_resource(name):
    """Serve gzipped reference data referenced by the manifest's `resources` block."""
    body = ts_local.resource_bytes(name)
    if body is None:
        return jsonify({"error": "Resource not found"}), 404
    return Response(body, mimetype="application/octet-stream", headers=_GZIP_HEADERS)


@ts_bp.route("/vbr/<reciter>")
def ts_vbr(reciter):
    """Return VBR chapters for timestamp clients reading older HF manifests."""
    return jsonify({"vbr_chapters": vbr_chapters_for_reciter(reciter)})


@ts_bp.route("/validate/<reciter>")
def ts_validate(reciter):
    """Validate timestamp data via the timestamps validator.

    Gated behind ``INSPECTOR_TS_VALIDATE_ENABLED`` (default ``1`` for local).
    Deployed Spaces flip it to ``0``; the route depends on the on-disk
    timestamps tree which doesn't exist in the bucket layout.
    """
    if os.environ.get("INSPECTOR_TS_VALIDATE_ENABLED", "1") != "1":
        return jsonify({
            "error": "ts_validate is disabled in deployed mode "
                     "(see INSPECTOR_TS_VALIDATE_ENABLED)"
        }), 410

    from validators.validate_timestamps import validate_reciter as _validate_ts
    from validators.validate_timestamps import load_word_counts as _load_ts_wc

    ts_dir = None
    for audio_type in reversed(TS_AUDIO_CATEGORIES):
        candidate = TIMESTAMPS_PATH / audio_type / reciter
        if (candidate / "timestamps.json").exists():
            ts_dir = candidate
            break
    if ts_dir is None:
        return jsonify({"error": "Reciter not found"}), 404

    wc = _load_ts_wc(SURAH_INFO_PATH)
    result = _validate_ts(ts_dir, wc)

    if result.get("skipped"):
        return jsonify({"error": "timestamps.json not found"}), 404

    mfa_failures = []
    for fail in result.get("_mfa_failures", []):
        vk = fail.get("verse", "")
        ch = int(vk.split(":")[0]) if vk and ":" in vk else 0
        ref = fail.get("ref", "?")
        mfa_failures.append({
            "verse_key": vk, "chapter": ch,
            "ref": ref, "seg": fail.get("seg", "?"),
            "error": fail.get("error", "?"),
            "diff_ms": 0,
            "label": f"{vk} [{ref}]",
        })

    missing_words = []
    for mw in result.get("_missing_words", []):
        vk = f"{mw['surah']}:{mw['ayah']}"
        count = len(mw["missing"])
        missing_words.append({
            "verse_key": vk, "chapter": mw["surah"],
            "missing": mw["missing"], "count": count,
            "diff_ms": count * MISSING_WORD_DIFF_MS_WEIGHT,
            "label": f"{vk} [-{count}w]",
        })
    missing_words.sort(key=lambda x: (x["chapter"],
                                      int(x["verse_key"].split(":")[1])
                                      if ":" in x["verse_key"] else 0))

    boundary_mismatches = []
    for bm in result.get("_boundary_mismatches", []):
        parts = bm["verse_key"].split(":")
        ch = int(parts[0]) if parts else 0
        boundary_mismatches.append({
            "verse_key": bm["verse_key"], "chapter": ch,
            "side": bm["side"], "diff_ms": bm["diff_ms"],
            "label": f"{bm['verse_key']} [{bm['diff_ms']}ms {bm['side']}]",
        })
    boundary_mismatches.sort(key=lambda x: x["diff_ms"], reverse=True)

    missing_verses = []
    for vk in result.get("_missing_verses", []):
        parts = vk.split(":")
        ch = int(parts[0]) if parts and parts[0].isdigit() else 0
        missing_verses.append({
            "verse_key": vk, "chapter": ch,
            "label": vk,
        })
    missing_verses.sort(key=lambda x: (x["chapter"],
        int(x["verse_key"].split(":")[1]) if ":" in x["verse_key"] else 0))

    verse_overlaps = []
    for ov in result.get("_verse_overlaps", []):
        parts = ov["verse_key"].split(":")
        ch = int(parts[0]) if parts else 0
        verse_overlaps.append({
            "verse_key": ov["verse_key"], "chapter": ch,
            "prev_verse_key": ov["prev_verse_key"],
            "overlap_ms": ov["overlap_ms"],
            "label": f"{ov['verse_key']} [-{ov['overlap_ms']}ms]",
        })
    verse_overlaps.sort(key=lambda x: x["overlap_ms"], reverse=True)

    large_gaps = []
    for g in result.get("_large_gaps", []):
        parts = g["verse_key"].split(":")
        ch = int(parts[0]) if parts else 0
        large_gaps.append({
            "verse_key": g["verse_key"], "chapter": ch,
            "prev_verse_key": g["prev_verse_key"],
            "gap_ms": g["gap_ms"],
            "label": f"{g['verse_key']} [{g['gap_ms']/1000:.1f}s gap]",
        })
    large_gaps.sort(key=lambda x: x["gap_ms"], reverse=True)

    return jsonify({
        "mfa_failures": mfa_failures,
        "missing_verses": missing_verses,
        "missing_words": missing_words,
        "verse_overlaps": verse_overlaps,
        "boundary_mismatches": boundary_mismatches,
        "large_gaps": large_gaps,
        "meta": {
            "has_segments": result.get("has_segments", False),
            "tolerance_ms": result.get("seg_tolerance_ms", TS_BOUNDARY_TOLERANCE_MS),
        },
    })
