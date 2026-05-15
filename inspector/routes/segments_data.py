"""Segments tab data routes (/api/seg/ — read-only data endpoints)."""

from flask import Blueprint, jsonify, request

from config import (
    SEG_FONT_SIZE, SEG_WORD_SPACING,
    SEG_SCROLL_ANIM_MODE,
    TRIM_PAD_LEFT, TRIM_PAD_RIGHT, TRIM_DIM_ALPHA,
    SHOW_BOUNDARY_PHONEMES,
    LOW_CONF_DEFAULT_THRESHOLD,
    ACCORDION_CONTEXT,
)
from constants import (
    MUQATTAAT_VERSES as _MUQATTAAT_VERSES,
    QALQALA_LETTERS as _QALQALA_LETTERS,
    STANDALONE_REFS as _STANDALONE_REFS,
    STANDALONE_WORDS as _STANDALONE_WORDS,
)
from services.validation.registry import ALL_CATEGORIES
from services import cache, data_dir
from services import state as state_service
from services.data_loader import (
    load_detailed,
    resolve_pad,
)
from services.audio_meta import vbr_chapters_for_reciter
from services.segments_query import get_chapter_data
from utils.formatting import slug_to_name
from utils.json_response import orjson_response
from utils.references import chapter_from_ref
from utils.uuid7 import uuid7

seg_data_bp = Blueprint("seg_data", __name__, url_prefix="/api/seg")


@seg_data_bp.route("/config")
def seg_config():
    """Return display configuration for Segments tab."""
    return orjson_response(
        {
            "seg_font_size": SEG_FONT_SIZE,
            "seg_word_spacing": SEG_WORD_SPACING,
            "seg_scroll_anim_mode": SEG_SCROLL_ANIM_MODE,
            "trim_pad_left": TRIM_PAD_LEFT,
            "trim_pad_right": TRIM_PAD_RIGHT,
            "trim_dim_alpha": TRIM_DIM_ALPHA,
            "show_boundary_phonemes": SHOW_BOUNDARY_PHONEMES,
            "low_conf_default_threshold": LOW_CONF_DEFAULT_THRESHOLD,
            "validation_categories": list(ALL_CATEGORIES),
            "muqattaat_verses": sorted([list(t) for t in _MUQATTAAT_VERSES]),
            "qalqala_letters": sorted(_QALQALA_LETTERS),
            "standalone_refs": sorted([list(t) for t in _STANDALONE_REFS]),
            "standalone_words": sorted(_STANDALONE_WORDS),
            "accordion_context": ACCORDION_CONTEXT,
        },
        # Static config keyed off process restart — minute-long client cache
        # is safe (changing a constant requires a restart anyway).
        headers={"Cache-Control": "private, max-age=60"},
    )


@seg_data_bp.route("/reciters")
def seg_reciters():
    """List reciters tracked in the state file.

    Reads from ``state_service.all_rows()`` instead of walking
    ``data/recitation_segments/`` so the segments tab surfaces every
    lifecycle phase (catalogued / awaiting_alignment / awaiting_review /
    under_review / awaiting_timestamps / released / completed). The
    bucket-resident ``segments.json`` is fetched per-row to populate
    ``audio_source`` (matches the v1 response shape).
    """
    # Lifecycle-volatile (claims, state transitions). Short TTL only so a
    # client doesn't keep stale "awaiting_review" rows across edits, but
    # repeat reloads inside ~30 s skip the per-row segments_doc fetch loop.
    headers = {"Cache-Control": "private, max-age=30"}
    cached = cache.get_seg_reciters_cache()
    if cached is not None:
        return orjson_response(cached, headers=headers)
    result = []
    for row in sorted(state_service.all_rows(), key=lambda r: r.slug):
        slug = row.slug
        audio_source = ""
        seg_doc = data_dir.read_segments_doc(slug)
        if seg_doc is not None:
            audio_source = seg_doc.get("_meta", {}).get("audio_source", "")
        result.append(
            {
                "slug": slug,
                "name": slug_to_name(slug),
                "audio_source": audio_source,
                "state": row.state.value,
                "visibility": row.visibility.value,
            }
        )
    cache.set_seg_reciters_cache(result)
    return orjson_response(result, headers=headers)


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
    """Return segments, audio URL, summary, and issues for a chapter.

    Sets ``Cache-Control: public, max-age=86400`` so a CDN (or browser cache)
    can hold this for a day. Not ``immutable``: shards mutate on re-edit, and
    edits do not currently cache-bust this URL. Cache life mirrors a typical
    review cycle — a contributor's claim usually lasts a day or two; the shard
    rarely changes mid-session, and the small staleness window is acceptable.
    """
    verse_filter = request.args.get("verse")
    result = get_chapter_data(reciter, chapter, verse_filter)
    if result is None:
        return jsonify({"error": "Chapter not found"}), 404
    response = jsonify(result)
    # When verse_filter is set the response is a slice — still safe for a CDN
    # because the URL key includes ?verse=… and the shape stays identical.
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


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
            # `matched_text` and `audio_url` deliberately omitted:
            # - `matched_text` is reconstructable client-side via
            #   ``dkTextForRef($quranRefs, matched_ref)`` and is the single
            #   biggest wire contributor (~315 KB brotli savings).
            # - `audio_url` is redundant with the top-level
            #   ``audio_by_chapter[chapter]`` map; every FE consumer already
            #   falls back to it.
            seg_dict = {
                "chapter":      ch,
                "entry_idx":    entry_idx,
                "index":        idx,
                "segment_uid":  seg_uid,
                "time_start":   seg.get("time_start", 0),
                "time_end":     seg.get("time_end", 0),
                "matched_ref":  mref,
                "confidence":   round(seg.get("confidence", 0.0), 4),
                "entry_ref":    entry.get("ref", ""),
            }
            if seg.get("wrap_word_ranges"):
                seg_dict["wrap_word_ranges"] = seg["wrap_word_ranges"]
            if seg.get("ignored_categories"):
                seg_dict["ignored_categories"] = seg["ignored_categories"]
            elif seg.get("ignored"):
                seg_dict["ignored_categories"] = ["_all"]
            segments.append(seg_dict)

    pad_left_ms, pad_right_ms, min_silence_floor_ms = resolve_pad(
        cache.get_seg_meta(reciter)
    )
    # dk_words + verse_word_counts moved off this payload to the immutable
    # ``/api/static/quran-refs.json`` asset (fetched once per browser).
    return orjson_response({
        "segments": segments,
        "audio_by_chapter": audio_by_chapter,
        "reciter_vbr_chapters": vbr_chapters_for_reciter(reciter),
        # Legacy symmetric shim: total padding == 2 * pad_ms ≈ pad_left + pad_right.
        "pad_ms": (pad_left_ms + pad_right_ms) // 2,
        "pad_left_ms": pad_left_ms,
        "pad_right_ms": pad_right_ms,
        "min_silence_floor_ms": min_silence_floor_ms,
    })
