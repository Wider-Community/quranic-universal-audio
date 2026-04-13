"""Segments tab data routes (/api/seg/ — read-only data endpoints)."""
import json

from flask import Blueprint, jsonify, request

from config import (
    RECITATION_SEGMENTS_PATH,
    SEG_FONT_SIZE, SEG_WORD_SPACING,
    TRIM_PAD_LEFT, TRIM_PAD_RIGHT, TRIM_DIM_ALPHA,
    SHOW_BOUNDARY_PHONEMES,
    LOW_CONF_DEFAULT_THRESHOLD,
    ACCORDION_CONTEXT,
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
from services.segments_query import get_chapter_data
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
        "accordion_context": ACCORDION_CONTEXT,
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
    verse_filter = request.args.get("verse")
    result = get_chapter_data(reciter, chapter, verse_filter)
    if result is None:
        return jsonify({"error": "Chapter not found"}), 404
    return jsonify(result)


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
