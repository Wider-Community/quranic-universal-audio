"""Timestamps tab routes (/api/ts/*)."""
import random
import sys
from pathlib import Path

from flask import Blueprint, jsonify, request

from config import (
    UNIFIED_DISPLAY_MAX_HEIGHT,
    ANIM_HIGHLIGHT_COLOR, ANIM_WORD_TRANSITION_DURATION,
    ANIM_CHAR_TRANSITION_DURATION, ANIM_TRANSITION_EASING,
    ANIM_WORD_SPACING, ANIM_LINE_HEIGHT, ANIM_FONT_SIZE,
    ANALYSIS_WORD_FONT_SIZE, ANALYSIS_LETTER_FONT_SIZE,
    TIMESTAMPS_PATH,
)
from services.data_loader import (
    discover_ts_reciters,
    load_audio_urls,
    load_timestamps,
    load_qpc,
    load_dk,
)
from utils.formatting import format_ms

# ── Validators path setup (for timestamp validation route) ─────────────────
_VALIDATORS_DIR = Path(__file__).resolve().parent.parent.parent / "validators"
if str(_VALIDATORS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_VALIDATORS_DIR.parent))

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
    data = load_timestamps(reciter)
    if not data:
        return jsonify({"error": "Reciter not found"}), 404
    verse = data["verses"].get(verse_ref)
    if verse is None:
        return jsonify({"error": "Verse not found"}), 404

    qpc = load_qpc()
    dk = load_dk()
    chapter = int(verse_ref.split(":")[0])

    # Build flat intervals list from per-word phones
    words_raw = verse.get("words", []) if isinstance(verse, dict) else verse
    intervals = []
    words_out = []

    is_compound = "-" in verse_ref
    if is_compound:
        start_part, end_part = verse_ref.split("-", 1)
        sp = start_part.split(":")
        ep = end_part.split(":")
        compound_surah = int(sp[0])
        compound_start_ayah = int(sp[1])
        compound_end_ayah = int(ep[1])
    else:
        compound_surah = compound_start_ayah = compound_end_ayah = 0

    cur_ayah = compound_start_ayah if is_compound else 0
    prev_word_idx = -1

    for w in words_raw:
        word_idx = w[0]
        w_start = w[1] / 1000
        w_end = w[2] / 1000
        letters_raw = w[3] if len(w) > 3 else []
        word_phones_raw = w[4] if len(w) > 4 else []

        if is_compound:
            if prev_word_idx >= 0 and word_idx <= prev_word_idx and cur_ayah < compound_end_ayah:
                cur_ayah += 1
            location = f"{compound_surah}:{cur_ayah}:{word_idx}"
            prev_word_idx = word_idx
        else:
            location = f"{verse_ref}:{word_idx}"
        text = qpc.get(location, {}).get("text", "")
        display_text = dk.get(location, {}).get("text", text)

        letters = []
        for lt in letters_raw:
            letters.append({
                "char": lt[0],
                "start": lt[1] / 1000 if lt[1] is not None else None,
                "end": lt[2] / 1000 if lt[2] is not None else None,
            })

        phone_start_idx = len(intervals)
        for ph in word_phones_raw:
            intervals.append({
                "phone": ph[0],
                "start": ph[1] / 1000,
                "end": ph[2] / 1000,
            })
        phoneme_indices = list(range(phone_start_idx, len(intervals)))

        words_out.append({
            "location": location,
            "text": text,
            "display_text": display_text,
            "start": w_start,
            "end": w_end,
            "phoneme_indices": phoneme_indices,
            "letters": letters,
        })

    # Audio URL
    audio_source = data["meta"].get("audio_source", "")
    audio_reciter = data["meta"].get("audio_reciter", reciter)
    audio_url = ""
    if audio_source:
        urls = load_audio_urls(audio_source, audio_reciter)
        audio_url = urls.get(verse_ref, urls.get(str(chapter), ""))

    audio_category = data.get("audio_category", "by_ayah_audio")
    time_start_ms = 0
    time_end_ms = 0

    if audio_category == "by_surah_audio":
        if words_raw:
            time_start_ms = words_raw[0][1]
            time_end_ms = words_raw[-1][2]
            offset_s = time_start_ms / 1000
            for word_obj in words_out:
                word_obj["start"] -= offset_s
                word_obj["end"] -= offset_s
                for lt in word_obj["letters"]:
                    if lt["start"] is not None:
                        lt["start"] -= offset_s
                    if lt["end"] is not None:
                        lt["end"] -= offset_s
            for iv in intervals:
                iv["start"] -= offset_s
                iv["end"] -= offset_s
    else:
        if intervals:
            time_end_ms = round(intervals[-1]["end"] * 1000)
        elif words_raw:
            time_end_ms = words_raw[-1][2]

    return jsonify({
        "reciter": reciter,
        "chapter": chapter,
        "verse_ref": verse_ref,
        "audio_url": audio_url,
        "time_start_ms": time_start_ms,
        "time_end_ms": time_end_ms,
        "intervals": intervals,
        "words": words_out,
    })


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

    surah_info_path = Path(__file__).resolve().parent.parent.parent / "data" / "surah_info.json"
    wc = _load_ts_wc(surah_info_path)
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
