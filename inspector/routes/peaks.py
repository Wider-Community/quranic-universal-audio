"""Waveform peaks routes (/api/seg/peaks)."""
import threading

from flask import Blueprint, jsonify, request

from services import cache
from services.data_loader import load_detailed
from services.peaks import get_peaks_for_reciter, compute_segment_peaks
from utils.references import chapter_from_ref

peaks_bp = Blueprint("peaks", __name__, url_prefix="/api/seg")


@peaks_bp.route("/peaks/<reciter>")
def seg_peaks(reciter):
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

    cached_only = request.args.get("cached_only", "").lower() == "true"

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
    if not complete and not cached_only and not cache.is_peaks_computing(cache_key):
        cache.add_peaks_computing(cache_key)

        def _bg():
            try:
                get_peaks_for_reciter(reciter, chapter_filter)
            finally:
                cache.discard_peaks_computing(cache_key)

        threading.Thread(target=_bg, daemon=True).start()

    return jsonify({"peaks": result, "complete": complete})


@peaks_bp.route("/segment-peaks/<reciter>", methods=["POST"])
def seg_segment_peaks(reciter):
    """Fetch peaks for individual segments via HTTP Range requests."""
    body = request.get_json(silent=True) or {}
    segments = body.get("segments", [])
    cached_only = body.get("cached_only", False)
    results = {}
    for seg in segments:
        url = seg.get("url", "")
        start_ms = seg.get("start_ms", 0)
        end_ms = seg.get("end_ms", 0)
        if not url or end_ms <= start_ms:
            continue
        key = f"{url}:{start_ms}:{end_ms}"
        data = compute_segment_peaks(url, start_ms, end_ms, reciter, cached_only=cached_only)
        if data:
            results[key] = data
    return jsonify({"peaks": results})
