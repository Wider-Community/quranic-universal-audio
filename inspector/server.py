"""
Alignment Inspector Server

Flask server for browsing alignment timestamps, recitation segments, and audio.
Route handlers are thin wrappers around services/ modules.
"""
import argparse
import concurrent.futures
import json
import random
import statistics
import sys
import threading
from collections import Counter
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

from constants import (
    VALIDATION_CATEGORIES,
    MUQATTAAT_VERSES as _MUQATTAAT_VERSES,
    QALQALA_LETTERS as _QALQALA_LETTERS,
    STANDALONE_REFS as _STANDALONE_REFS,
    STANDALONE_WORDS as _STANDALONE_WORDS,
)
from config import (
    AUDIO_METADATA_PATH, AUDIO_PATH, CACHE_DIR,
    RECITATION_SEGMENTS_PATH,
    UNIFIED_DISPLAY_MAX_HEIGHT,
    ANIM_HIGHLIGHT_COLOR, ANIM_WORD_TRANSITION_DURATION,
    ANIM_CHAR_TRANSITION_DURATION, ANIM_TRANSITION_EASING,
    ANIM_WORD_SPACING, ANIM_LINE_HEIGHT, ANIM_FONT_SIZE,
    ANALYSIS_WORD_FONT_SIZE, ANALYSIS_LETTER_FONT_SIZE,
    SEG_FONT_SIZE, SEG_WORD_SPACING,
    TRIM_PAD_LEFT, TRIM_PAD_RIGHT, TRIM_DIM_ALPHA,
    SHOW_BOUNDARY_PHONEMES,
    LOW_CONF_DEFAULT_THRESHOLD,
    LOW_CONFIDENCE_THRESHOLD,
    AUDIO_CACHE_MAX_AGE,
    TIMESTAMPS_PATH,
)

from services import cache
from services.data_loader import (
    discover_ts_reciters,
    dk_text_for_ref,
    get_word_counts,
    load_audio_sources,
    load_audio_urls,
    load_detailed,
    load_seg_verses,
    load_surah_info_lite,
    load_timestamps,
    load_qpc,
    load_dk,
)
from services.phonemizer_service import (
    get_canonical_phonemes,
    get_phonemizer,
    has_phonemizer,
)
from services.validation import (
    chapter_validation_counts,
    is_ignored_for,
    run_validation_log,
    validate_reciter_segments,
)
from services.peaks import (
    compute_audio_peaks,
    get_peaks_for_reciter,
)
from services.audio_proxy import (
    delete_audio_cache,
    download_audio,
    scan_audio_cache,
)
from services.save import save_seg_data as _save_seg_data
from services.undo import undo_batch as _undo_batch, undo_ops as _undo_ops
from services.stats import compute_stats
from utils.references import chapter_from_ref
from utils.uuid7 import uuid7

# ── Validators path setup (for timestamp validation route) ─────────────────
_VALIDATORS_DIR = Path(__file__).resolve().parent.parent / "validators"
if str(_VALIDATORS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_VALIDATORS_DIR.parent))


app = Flask(__name__, static_folder="static")

# ---------------------------------------------------------------------------
# Static / index routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Serve the main HTML page."""
    return send_from_directory("static", "index.html")


@app.route("/static/<path:filename>")
def serve_static(filename):
    """Serve static files."""
    return send_from_directory("static", filename)


# ---------------------------------------------------------------------------
# Config routes
# ---------------------------------------------------------------------------

@app.route("/api/ts/config")
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


@app.route("/api/seg/config")
def seg_config():
    """Return display configuration for Segments tab."""
    return jsonify({
        "seg_font_size": SEG_FONT_SIZE,
        "seg_word_spacing": SEG_WORD_SPACING,
        "trim_pad_left": TRIM_PAD_LEFT,
        "trim_pad_right": TRIM_PAD_RIGHT,
        "trim_dim_alpha": TRIM_DIM_ALPHA,
        "show_boundary_phonemes": SHOW_BOUNDARY_PHONEMES,
        "low_conf_default_threshold": LOW_CONF_DEFAULT_THRESHOLD,
        "validation_categories": list(VALIDATION_CATEGORIES),
        "muqattaat_verses": sorted([list(t) for t in _MUQATTAAT_VERSES]),
        "qalqala_letters": sorted(_QALQALA_LETTERS),
        "standalone_refs": sorted([list(t) for t in _STANDALONE_REFS]),
        "standalone_words": sorted(_STANDALONE_WORDS),
    })


@app.route("/api/surah-info")
def get_surah_info():
    """Return lightweight surah metadata."""
    return jsonify(load_surah_info_lite())


# ---------------------------------------------------------------------------
# Timestamps tab
# ---------------------------------------------------------------------------

@app.route("/api/ts/reciters")
def get_ts_reciters():
    """Return list of reciters with timestamps data."""
    return jsonify(discover_ts_reciters())


@app.route("/api/ts/chapters/<reciter>")
def get_ts_chapters(reciter):
    """Return sorted list of chapter numbers derived from verse keys."""
    data = load_timestamps(reciter)
    if not data:
        return jsonify({"error": "Reciter not found"}), 404
    chapters = sorted(set(int(k.split(":")[0]) for k in data["verses"]))
    return jsonify(chapters)


@app.route("/api/ts/verses/<reciter>/<int:chapter>")
def get_ts_verses(reciter, chapter):
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


@app.route("/api/ts/data/<reciter>/<verse_ref>")
def get_ts_data(reciter, verse_ref):
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


@app.route("/api/ts/random")
def get_ts_random():
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
        return get_ts_data(r["slug"], verse_ref)
    return jsonify({"error": "No verses found"}), 500


@app.route("/api/ts/random/<reciter>")
def get_ts_random_reciter(reciter):
    """Pick a random verse from the specified reciter and return full data."""
    data = load_timestamps(reciter)
    if not data or not data["verses"]:
        return jsonify({"error": f"No timestamps data for reciter '{reciter}'"}), 404
    verse_ref = random.choice(list(data["verses"].keys()))
    return get_ts_data(reciter, verse_ref)


@app.route("/api/ts/validate/<reciter>")
def validate_ts_reciter(reciter):
    """Validate timestamp data via the timestamps validator."""
    from validators.validate_timestamps import validate_reciter as _validate_ts
    from validators.validate_timestamps import load_word_counts as _load_ts_wc
    from utils.formatting import format_ms

    ts_dir = None
    for audio_type in ("by_surah_audio", "by_ayah_audio"):
        candidate = TIMESTAMPS_PATH / audio_type / reciter
        if (candidate / "timestamps.json").exists():
            ts_dir = candidate
            break
    if ts_dir is None:
        return jsonify({"error": "Reciter not found"}), 404

    surah_info_path = Path(__file__).resolve().parent.parent / "data" / "surah_info.json"
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


@app.route("/audio/<reciter>/<filename>")
def serve_audio(reciter, filename):
    """Serve audio files."""
    audio_path = AUDIO_PATH / reciter / filename
    if not audio_path.exists():
        return jsonify({"error": "Audio file not found"}), 404
    mime_types = {
        ".flac": "audio/flac",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
    }
    mime_type = mime_types.get(audio_path.suffix.lower(), "audio/mpeg")
    return send_file(audio_path, mimetype=mime_type)


# ---------------------------------------------------------------------------
# Segments tab
# ---------------------------------------------------------------------------

@app.route("/api/seg/reciters")
def get_seg_reciters():
    """List reciters that have segment extraction results."""
    cached = cache.get_seg_reciters_cache()
    if cached is not None:
        return jsonify(cached)
    if not RECITATION_SEGMENTS_PATH.exists():
        return jsonify([])
    result = []
    for d in sorted(RECITATION_SEGMENTS_PATH.iterdir(), key=lambda p: p.name):
        if not d.is_dir() or not (d / "detailed.json").exists():
            continue
        slug = d.name
        name = slug.replace("_", " ").title()
        audio_source = ""
        seg_path = d / "segments.json"
        if seg_path.exists():
            with open(seg_path, encoding="utf-8") as f:
                try:
                    seg_doc = json.load(f)
                    audio_source = seg_doc.get("_meta", {}).get("audio_source", "")
                except json.JSONDecodeError:
                    pass
        result.append({"slug": slug, "name": name, "audio_source": audio_source})
    cache.set_seg_reciters_cache(result)
    return jsonify(result)


@app.route("/api/seg/chapters/<reciter>")
def get_seg_chapters(reciter):
    """Return list of chapter numbers available for a reciter."""
    entries = load_detailed(reciter)
    if not entries:
        return jsonify({"error": "Reciter not found"}), 404
    chapters = sorted(set(chapter_from_ref(e["ref"]) for e in entries))
    return jsonify(chapters)


@app.route("/api/seg/data/<reciter>/<int:chapter>")
def get_seg_data(reciter, chapter):
    """Return segments, audio URL, summary, and issues for a chapter."""
    entries = load_detailed(reciter)
    matching = [e for e in entries if chapter_from_ref(e["ref"]) == chapter]
    if not matching:
        return jsonify({"error": "Chapter not found"}), 404

    audio_url = matching[0].get("audio", "")

    segments = []
    idx = 0
    for entry_idx, entry in enumerate(matching):
        entry_audio = entry.get("audio", "")
        for seg in entry.get("segments", []):
            t_start = seg.get("time_start", 0)
            t_end = seg.get("time_end", 0)
            mref = seg.get("matched_ref", "")
            seg_dict = {
                "index": idx,
                "entry_idx": entry_idx,
                "time_start": t_start,
                "time_end": t_end,
                "matched_ref": mref,
                "matched_text": seg.get("matched_text", ""),
                "display_text": dk_text_for_ref(mref),
                "confidence": round(seg.get("confidence", 0.0), 4),
                "audio_url": entry_audio,
            }
            if seg.get("ignored_categories"):
                seg_dict["ignored_categories"] = seg["ignored_categories"]
            elif seg.get("ignored"):
                seg_dict["ignored_categories"] = ["_all"]
            segments.append(seg_dict)
            idx += 1

    verse_filter = request.args.get("verse")
    if verse_filter:
        prefix = f"{chapter}:{verse_filter}:"
        segments = [s for s in segments if s["matched_ref"].startswith(prefix)]

    matched = [s for s in segments if s["matched_ref"]]
    failed = [s for s in segments if not s["matched_ref"]]
    confidences = [s["confidence"] for s in matched]

    speech_durations = [s["time_end"] - s["time_start"] for s in segments]
    total_speech = sum(speech_durations)
    pad_ms = cache.get_seg_meta(reciter).get("pad_ms", 0)
    silence_durations = []
    for i in range(len(segments) - 1):
        if segments[i]["entry_idx"] == segments[i + 1]["entry_idx"]:
            gap = segments[i + 1]["time_start"] - segments[i]["time_end"] + 2 * pad_ms
            if gap > 0:
                silence_durations.append(gap)
    total_silence = sum(silence_durations)

    issue_indices = []
    for s in segments:
        if not s["matched_ref"]:
            issue_indices.append(s["index"])
        elif s["confidence"] < 0.60:
            issue_indices.append(s["index"])

    # Missing verses
    missing_verses = []
    wc = get_word_counts()
    expected_verses = {v for (s, v) in wc if s == chapter}
    if expected_verses:
        found_verses = set()
        for s in segments:
            ref = s["matched_ref"]
            if ref:
                parts = ref.split("-")
                if len(parts) == 2:
                    start = parts[0].split(":")
                    end = parts[1].split(":")
                    if len(start) >= 2:
                        try:
                            for v in range(int(start[1]), int(end[1]) + 1):
                                found_verses.add(v)
                        except (ValueError, IndexError):
                            pass
        missing_verses = sorted(expected_verses - found_verses)

    summary = {
        "total_segments": len(segments),
        "matched_segments": len(matched),
        "failed_segments": len(failed),
        "conf_min": round(min(confidences), 4) if confidences else 0,
        "conf_median": round(statistics.median(confidences), 4) if confidences else 0,
        "conf_mean": round(statistics.mean(confidences), 4) if confidences else 0,
        "conf_max": round(max(confidences), 4) if confidences else 0,
        "below_60": sum(1 for c in confidences if c < 0.60),
        "below_80": sum(1 for c in confidences if c < LOW_CONFIDENCE_THRESHOLD),
        "total_speech_ms": round(total_speech),
        "avg_segment_ms": round(total_speech / len(segments)) if segments else 0,
        "total_silence_ms": round(total_silence),
        "avg_silence_ms": round(total_silence / len(silence_durations)) if silence_durations else 0,
        "issue_indices": issue_indices,
        "missing_verses": [f"{chapter}:{v}" for v in missing_verses],
    }

    verse_word_counts = {}
    for (s, v), n in wc.items():
        if s == chapter:
            verse_word_counts[f"{chapter}:{v}"] = n

    return jsonify({
        "audio_url": audio_url,
        "segments": segments,
        "summary": summary,
        "verse_word_counts": verse_word_counts,
    })


@app.route("/api/seg/all/<reciter>")
def get_seg_all(reciter):
    """Return all segments across all chapters for a reciter."""
    entries = load_detailed(reciter)
    if not entries:
        return jsonify({"error": "Reciter not found"}), 404

    segments = []
    audio_by_chapter = {}
    chapter_seg_idx = {}

    for entry_idx, entry in enumerate(entries):
        ch = chapter_from_ref(entry["ref"])
        entry_audio = entry.get("audio", "")
        if str(ch) not in audio_by_chapter:
            audio_by_chapter[str(ch)] = entry_audio
        for seg in entry.get("segments", []):
            idx = chapter_seg_idx.get(ch, 0)
            chapter_seg_idx[ch] = idx + 1
            mref = seg.get("matched_ref", "")
            seg_uid = seg.get("segment_uid") or ""
            if not seg_uid:
                seg_uid = uuid7()
                seg["segment_uid"] = seg_uid
            seg_dict = {
                "chapter":      ch,
                "entry_idx":    entry_idx,
                "index":        idx,
                "segment_uid":  seg_uid,
                "time_start":   seg.get("time_start", 0),
                "time_end":     seg.get("time_end", 0),
                "matched_ref":  mref,
                "matched_text": seg.get("matched_text", ""),
                "display_text": dk_text_for_ref(mref),
                "confidence":   round(seg.get("confidence", 0.0), 4),
                "audio_url":    entry_audio,
                "entry_ref":    entry.get("ref", ""),
            }
            if seg.get("wrap_word_ranges"):
                seg_dict["wrap_word_ranges"] = seg["wrap_word_ranges"]
            if seg.get("ignored_categories"):
                seg_dict["ignored_categories"] = seg["ignored_categories"]
            elif seg.get("ignored"):
                seg_dict["ignored_categories"] = ["_all"]
            segments.append(seg_dict)

    verse_word_counts = {}
    for (surah, ayah), n in get_word_counts().items():
        verse_word_counts[f"{surah}:{ayah}"] = n

    return jsonify({
        "segments": segments,
        "audio_by_chapter": audio_by_chapter,
        "verse_word_counts": verse_word_counts,
        "pad_ms": cache.get_seg_meta(reciter).get("pad_ms", 0),
    })


# ---------------------------------------------------------------------------
# Peaks
# ---------------------------------------------------------------------------

@app.route("/api/seg/peaks/<reciter>")
def get_seg_peaks(reciter):
    """Return pre-computed waveform peaks for a reciter's audio files."""
    entries = load_detailed(reciter)
    if not entries:
        return jsonify({"error": "Reciter not found"}), 404

    chapters_param = request.args.get("chapters", "")
    chapter_filter = None
    if chapters_param:
        try:
            chapter_filter = {int(c) for c in chapters_param.split(",") if c.strip()}
        except ValueError:
            pass

    target_urls = set()
    for entry in entries:
        ch = chapter_from_ref(entry["ref"])
        if chapter_filter and ch not in chapter_filter:
            continue
        url = entry.get("audio", "")
        if url:
            target_urls.add(url)

    lock = cache.get_peaks_lock()
    with lock:
        cached = cache.get_peaks_cache(reciter)
    result = {u: cached[u] for u in target_urls if u in cached}
    complete = len(result) >= len(target_urls)

    cache_key = f"{reciter}:{chapters_param}"
    if not complete and not cache.is_peaks_computing(cache_key):
        cache.add_peaks_computing(cache_key)

        def _bg():
            try:
                get_peaks_for_reciter(reciter, chapter_filter)
            finally:
                cache.discard_peaks_computing(cache_key)

        threading.Thread(target=_bg, daemon=True).start()

    return jsonify({"peaks": result, "complete": complete})


# ---------------------------------------------------------------------------
# Audio proxy cache
# ---------------------------------------------------------------------------

@app.route("/api/seg/audio-proxy/<reciter>")
def audio_proxy(reciter):
    """Proxy and cache audio from CDN."""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "No url provided"}), 400
    cache_path = cache.audio_cache_path(reciter, url)
    if not cache_path.exists():
        result = download_audio(reciter, url)
        if not result:
            return jsonify({"error": "Download failed"}), 502
    mime_types = {
        ".mp3": "audio/mpeg", ".wav": "audio/wav",
        ".flac": "audio/flac", ".ogg": "audio/ogg",
    }
    mime = mime_types.get(cache_path.suffix.lower(), "audio/mpeg")
    resp = send_file(cache_path, mimetype=mime)
    resp.headers["Cache-Control"] = f"public, max-age={AUDIO_CACHE_MAX_AGE}, immutable"
    return resp


@app.route("/api/seg/audio-cache-status/<reciter>")
def audio_cache_status(reciter):
    """Return cache status for a reciter's audio files."""
    status = scan_audio_cache(reciter)
    if status["total"] == 0:
        return jsonify({"error": "Reciter not found"}), 404
    progress = cache.get_audio_dl_progress(reciter)
    return jsonify({
        **status,
        "downloading": progress and not progress.get("complete", False),
        "download_progress": progress,
    })


@app.route("/api/seg/prepare-audio/<reciter>", methods=["POST"])
def prepare_audio(reciter):
    """Start background download of all audio for a reciter."""
    entries = load_detailed(reciter)
    if not entries:
        return jsonify({"error": "Reciter not found"}), 404
    urls = {}
    for entry in entries:
        ch = chapter_from_ref(entry["ref"])
        url = entry.get("audio", "")
        if url and str(ch) not in urls:
            urls[str(ch)] = url
    to_download = {ch: u for ch, u in urls.items() if not cache.audio_cache_path(reciter, u).exists()}
    total = len(urls)
    already_cached = total - len(to_download)

    dl_lock = cache.get_audio_dl_lock()
    with dl_lock:
        existing = cache.get_audio_dl_progress(reciter)
        if existing and not existing.get("complete", False):
            return jsonify({"status": "already_running", **existing})
        cache.set_audio_dl_progress(reciter, {
            "total": total, "downloaded": already_cached, "complete": False
        })

    def _bg():
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(download_audio, reciter, u): ch for ch, u in to_download.items()}
            for future in concurrent.futures.as_completed(futures):
                with dl_lock:
                    prog = cache.get_audio_dl_progress(reciter)
                    if prog:
                        prog["downloaded"] = prog["downloaded"] + 1
            with dl_lock:
                prog = cache.get_audio_dl_progress(reciter)
                if prog:
                    prog["complete"] = True
            cache.pop_audio_cache_status(reciter)

    threading.Thread(target=_bg, daemon=True).start()
    return jsonify({"status": "started", "total": total, "to_download": len(to_download)})


@app.route("/api/seg/delete-audio-cache/<reciter>", methods=["DELETE"])
def delete_audio_cache_route(reciter):
    """Delete all cached data (audio + peaks) for a reciter."""
    result = delete_audio_cache(reciter)
    return jsonify(result)


# ---------------------------------------------------------------------------
# Segments: resolve ref, save, undo
# ---------------------------------------------------------------------------

@app.route("/api/seg/resolve_ref")
def resolve_ref():
    """Resolve a word-range reference to its Arabic text via the phonemizer."""
    ref = request.args.get("ref", "").strip()
    if not ref:
        return jsonify({"error": "No ref provided"}), 400
    if not has_phonemizer():
        return jsonify({"error": "Phonemizer not available"}), 503
    try:
        pm = get_phonemizer()
        result = pm.phonemize(ref=ref)
        mapping = result.get_mapping()
        text = " ".join(w.text for w in mapping.words)
        display_text = dk_text_for_ref(ref)
        return jsonify({"text": text, "display_text": display_text or text})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/seg/save/<reciter>/<int:chapter>", methods=["POST"])
def save_seg_data(reciter, chapter):
    """Save edited segments back to detailed.json and segments.json."""
    updates = request.get_json()
    if not updates or "segments" not in updates:
        return jsonify({"error": "Missing segments in request body"}), 400
    result = _save_seg_data(reciter, chapter, updates)
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@app.route("/api/seg/undo-batch/<reciter>", methods=["POST"])
def undo_seg_batch(reciter):
    """Undo a specific saved batch by reversing its operations."""
    body = request.get_json()
    if not body or not body.get("batch_id"):
        return jsonify({"error": "Missing batch_id"}), 400
    result = _undo_batch(reciter, body["batch_id"])
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@app.route("/api/seg/undo-ops/<reciter>", methods=["POST"])
def undo_seg_ops(reciter):
    """Undo specific operations within a saved batch."""
    body = request.get_json()
    if not body or not body.get("batch_id") or not body.get("op_ids"):
        return jsonify({"error": "Missing batch_id or op_ids"}), 400
    result = _undo_ops(reciter, body["batch_id"], set(body["op_ids"]))
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


# ---------------------------------------------------------------------------
# Validation + Stats
# ---------------------------------------------------------------------------

@app.route("/api/seg/trigger-validation/<reciter>", methods=["POST"])
def trigger_validation_log(reciter):
    """Kick off validation.log generation in background."""
    threading.Thread(
        target=lambda: run_validation_log(RECITATION_SEGMENTS_PATH / reciter),
        daemon=True,
    ).start()
    return jsonify({"ok": True})


@app.route("/api/seg/validate/<reciter>")
def validate_reciter_segments_route(reciter):
    """Validate all chapters for a reciter."""
    result = validate_reciter_segments(reciter)
    if result is None:
        return jsonify({"error": "Reciter not found"}), 404
    return jsonify(result)


@app.route("/api/seg/stats/<reciter>")
def get_seg_stats(reciter):
    """Return segmentation statistics and histogram distributions."""
    result = compute_stats(reciter)
    if result is None:
        return jsonify({"error": "Reciter not found"}), 404
    return jsonify(result)


@app.route("/api/seg/stats/<reciter>/save-chart", methods=["POST"])
def save_stat_chart(reciter):
    """Save a chart PNG to data/recitation_segments/<reciter>/analysis/."""
    seg_dir = RECITATION_SEGMENTS_PATH / reciter
    if not seg_dir.exists():
        return jsonify({"error": "Reciter not found"}), 404
    name = request.form.get("name", "chart")
    name = "".join(c for c in name if c.isalnum() or c in "-_").strip() or "chart"
    f = request.files.get("image")
    if not f:
        return jsonify({"error": "No image provided"}), 400
    out_dir = seg_dir / "analysis"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{name}.png"
    f.save(str(out_path))
    return jsonify({"ok": True, "path": str(out_path)})


# ---------------------------------------------------------------------------
# Edit history
# ---------------------------------------------------------------------------

@app.route("/api/seg/edit-history/<reciter>")
def get_seg_edit_history(reciter):
    """Return edit history batches and summary stats for the reciter."""
    history_path = RECITATION_SEGMENTS_PATH / reciter / "edit_history.jsonl"
    if not history_path.exists():
        return jsonify({"batches": [], "summary": None})

    # Parse all records
    all_records = []
    fully_reverted_ids: set[str] = set()
    per_op_reverted: dict[str, set[str]] = {}
    for line in history_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("record_type") == "genesis":
            continue
        all_records.append(record)
        rbid = record.get("reverts_batch_id")
        if rbid:
            rop_ids = record.get("reverts_op_ids")
            if rop_ids:
                if rbid not in per_op_reverted:
                    per_op_reverted[rbid] = set()
                per_op_reverted[rbid].update(rop_ids)
            else:
                fully_reverted_ids.add(rbid)

    batches = []
    op_counts: Counter = Counter()
    fix_kind_counts: Counter = Counter()
    chapters_edited: set[int] = set()
    total_batches = 0

    for record in all_records:
        if record.get("reverts_batch_id"):
            continue
        batch_id = record.get("batch_id")
        if batch_id in fully_reverted_ids:
            continue

        ops = record.get("operations", [])
        reverted_ops_for_batch = per_op_reverted.get(batch_id, set())
        if reverted_ops_for_batch:
            ops = [op for op in ops if op.get("op_id") not in reverted_ops_for_batch]
        if not ops and reverted_ops_for_batch:
            continue

        batch = {
            "batch_id": batch_id,
            "batch_type": record.get("batch_type"),
            "saved_at_utc": record.get("saved_at_utc"),
            "chapter": record.get("chapter"),
            "chapters": record.get("chapters"),
            "save_mode": record.get("save_mode"),
            "is_revert": False,
            "validation_summary_before": record.get("validation_summary_before"),
            "validation_summary_after": record.get("validation_summary_after"),
            "operations": ops,
        }
        if reverted_ops_for_batch:
            batch["reverted_op_ids"] = list(reverted_ops_for_batch)
        batches.append(batch)

        if ops:
            total_batches += 1
            ch = record.get("chapter")
            if ch is not None:
                chapters_edited.add(ch)
            for mch in record.get("chapters") or []:
                chapters_edited.add(mch)
            for op in ops:
                op_counts[op.get("op_type", "unknown")] += 1
                fix_kind_counts[op.get("fix_kind", "unknown")] += 1

    total_operations = sum(op_counts.values())
    summary = {
        "total_operations": total_operations,
        "total_batches": total_batches,
        "chapters_edited": len(chapters_edited),
        "op_counts": dict(op_counts),
        "fix_kind_counts": dict(fix_kind_counts),
    } if total_operations > 0 else None

    return jsonify({"batches": batches, "summary": summary})


# ---------------------------------------------------------------------------
# Audio tab
# ---------------------------------------------------------------------------

@app.route("/api/audio/sources")
def get_audio_sources():
    """Return hierarchical audio source structure."""
    return jsonify(load_audio_sources())


@app.route("/api/audio/surahs/<category>/<source>/<slug>")
def get_audio_surahs(category, source, slug):
    """Return surah/ayah URLs for a reciter within a specific source."""
    key = f"{category}/{source}/{slug}"
    cached = cache.get_audio_url_cache(key)
    if cached is not None:
        return jsonify({"surahs": cached})
    path = AUDIO_METADATA_PATH / category / source / f"{slug}.json"
    if not path.exists():
        return jsonify({"error": "Reciter not found"}), 404
    with open(path, encoding="utf-8") as f:
        surahs = json.load(f)
    surahs.pop("_meta", None)
    surahs = {k: (v["url"] if isinstance(v, dict) else v) for k, v in surahs.items()}
    cache.set_audio_url_cache(key, surahs)
    return jsonify({"surahs": surahs})


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Alignment Inspector Server")
    parser.add_argument("--port", type=int, default=5000, help="Port to run on")
    args = parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Eagerly initialize phonemizer
    if has_phonemizer():
        print("Initializing phonemizer...")
        get_phonemizer()
        print("Phonemizer ready.")
    else:
        print("Phonemizer not available (reference resolution disabled)")

    # Eagerly discover timestamp reciters
    reciters = discover_ts_reciters()
    print(f"Discovered {len(reciters)} timestamp reciter(s).")

    # Preload all timestamp data in background threads
    if reciters:
        def _preload(slug):
            load_timestamps(slug)
            return slug
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(reciters)) as pool:
            for slug in pool.map(_preload, [r["slug"] for r in reciters]):
                print(f"  Preloaded timestamps: {slug}")
        print("All timestamp data cached.")

    print(f"Starting server at http://localhost:{args.port}")
    app.run(host="0.0.0.0", port=args.port, debug=True, use_reloader=True,
            extra_files=[
                str(Path(__file__).parent / "static" / "segments.js"),
                str(Path(__file__).parent / "static" / "app.js"),
                str(Path(__file__).parent / "static" / "audio.js"),
                str(Path(__file__).parent / "static" / "style.css"),
                str(Path(__file__).parent / "static" / "index.html"),
            ])
