"""Segments tab data routes (/api/seg/ — read-only data endpoints)."""
import json
import statistics

from flask import Blueprint, jsonify, request

from config import (
    RECITATION_SEGMENTS_PATH,
    SEG_FONT_SIZE, SEG_WORD_SPACING,
    TRIM_PAD_LEFT, TRIM_PAD_RIGHT, TRIM_DIM_ALPHA,
    SHOW_BOUNDARY_PHONEMES,
    LOW_CONF_DEFAULT_THRESHOLD,
    LOW_CONFIDENCE_THRESHOLD,
)
from constants import (
    VALIDATION_CATEGORIES,
    MUQATTAAT_VERSES as _MUQATTAAT_VERSES,
    QALQALA_LETTERS as _QALQALA_LETTERS,
    STANDALONE_REFS as _STANDALONE_REFS,
    STANDALONE_WORDS as _STANDALONE_WORDS,
)
from services import cache
from services.data_loader import (
    dk_text_for_ref,
    get_word_counts,
    load_detailed,
)
from utils.references import chapter_from_ref
from utils.uuid7 import uuid7

seg_data_bp = Blueprint("seg_data", __name__, url_prefix="/api/seg")


@seg_data_bp.route("/config")
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


@seg_data_bp.route("/reciters")
def seg_reciters():
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


@seg_data_bp.route("/chapters/<reciter>")
def seg_chapters(reciter):
    """Return list of chapter numbers available for a reciter."""
    entries = load_detailed(reciter)
    if not entries:
        return jsonify({"error": "Reciter not found"}), 404
    chapters = sorted(set(chapter_from_ref(e["ref"]) for e in entries))
    return jsonify(chapters)


@seg_data_bp.route("/data/<reciter>/<int:chapter>")
def seg_data(reciter, chapter):
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


@seg_data_bp.route("/all/<reciter>")
def seg_all(reciter):
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
