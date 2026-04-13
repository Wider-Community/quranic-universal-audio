"""Timestamps tab routes (/api/ts/*)."""
import random

from flask import Blueprint, jsonify, request

from config import (
    UNIFIED_DISPLAY_MAX_HEIGHT,
    ANIM_HIGHLIGHT_COLOR, ANIM_WORD_TRANSITION_DURATION,
    ANIM_CHAR_TRANSITION_DURATION, ANIM_TRANSITION_EASING,
    ANIM_WORD_SPACING, ANIM_LINE_HEIGHT, ANIM_FONT_SIZE,
    ANALYSIS_WORD_FONT_SIZE, ANALYSIS_LETTER_FONT_SIZE,
    SURAH_INFO_PATH,
    TIMESTAMPS_PATH,
)
from services.data_loader import (
    discover_ts_reciters,
    load_audio_urls,
    load_timestamps,
)
from services.ts_query import get_verse_data
from utils.formatting import format_ms

ts_bp = Blueprint("ts", __name__, url_prefix="/api/ts")


@ts_bp.route("/config")
def ts_config():
    """Return display configuration for Timestamps tab."""
    return jsonify({
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


@ts_bp.route("/reciters")
def ts_reciters():
    """Return list of reciters with timestamps data."""
    return jsonify(discover_ts_reciters())


@ts_bp.route("/chapters/<reciter>")
def ts_chapters(reciter):
    """Return sorted list of chapter numbers derived from verse keys."""
    data = load_timestamps(reciter)
    if not data:
        return jsonify({"error": "Reciter not found"}), 404
    chapters = sorted(set(int(k.split(":")[0]) for k in data["verses"]))
    return jsonify(chapters)


@ts_bp.route("/verses/<reciter>/<int:chapter>")
def ts_verses(reciter, chapter):
    """Return verse refs and audio URLs for a chapter."""
    data = load_timestamps(reciter)
    if not data:
        return jsonify({"error": "Reciter not found"}), 404

    prefix = f"{chapter}:"
    verse_refs = sorted(
        (k for k in data["verses"] if k.startswith(prefix)),
        key=lambda k: int(k.split(":")[1]),
    )
    if not verse_refs:
        return jsonify({"error": "Chapter not found"}), 404

    audio_source = data["meta"].get("audio_source", "")
    audio_reciter = data["meta"].get("audio_reciter", reciter)
    urls = load_audio_urls(audio_source, audio_reciter) if audio_source else {}

    verses = []
    for ref in verse_refs:
        verses.append({
            "ref": ref,
            "audio_url": urls.get(ref, urls.get(str(chapter), "")),
        })
    return jsonify({"verses": verses})


@ts_bp.route("/data/<reciter>/<verse_ref>")
def ts_data(reciter, verse_ref):
    """Return full verse data for visualization."""
    result = get_verse_data(reciter, verse_ref)
    err = result.get("_error") if result else None
    if err == "reciter_not_found":
        return jsonify({"error": "Reciter not found"}), 404
    if err == "verse_not_found":
        return jsonify({"error": "Verse not found"}), 404
    return jsonify(result)


@ts_bp.route("/random")
def ts_random():
    """Pick a random verse from a random reciter and return full data."""
    reciters = discover_ts_reciters()
    if not reciters:
        return jsonify({"error": "No timestamps data"}), 500
    for _ in range(10):
        r = random.choice(reciters)
        data = load_timestamps(r["slug"])
        if not data or not data["verses"]:
            continue
        verse_ref = random.choice(list(data["verses"].keys()))
        return ts_data(r["slug"], verse_ref)
    return jsonify({"error": "No verses found"}), 500


@ts_bp.route("/random/<reciter>")
def ts_random_reciter(reciter):
    """Pick a random verse from the specified reciter and return full data."""
    data = load_timestamps(reciter)
    if not data or not data["verses"]:
        return jsonify({"error": f"No timestamps data for reciter '{reciter}'"}), 404
    verse_ref = random.choice(list(data["verses"].keys()))
    return ts_data(reciter, verse_ref)


@ts_bp.route("/validate/<reciter>")
def ts_validate(reciter):
    """Validate timestamp data via the timestamps validator."""
    from validators.validate_timestamps import validate_reciter as _validate_ts
    from validators.validate_timestamps import load_word_counts as _load_ts_wc

    ts_dir = None
    for audio_type in ("by_surah_audio", "by_ayah_audio"):
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
            "diff_ms": count * 1000,
            "label": f"{vk} [-{count}w]",
        })
    missing_words.sort(key=lambda x: x["diff_ms"], reverse=True)

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

    return jsonify({
        "mfa_failures": mfa_failures,
        "missing_words": missing_words,
        "boundary_mismatches": boundary_mismatches,
        "meta": {
            "has_segments": result.get("has_segments", False),
            "tolerance_ms": result.get("seg_tolerance_ms", 500),
        },
    })
