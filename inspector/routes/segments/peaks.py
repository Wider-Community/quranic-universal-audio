"""Waveform peaks routes (/api/seg/peaks).

Cache-Control strategy: peaks are deterministic for a given (reciter, chapter,
segment-range) but the response body changes when a reviewer edits segment
boundaries. The frontend appends ``?h=<hash>`` to peaks URLs computed from
the source content (segment boundaries, audio URL). When the source changes,
the hash changes, which is a fresh cache key.

- ``?h=<sha>`` present → ``public, max-age=31536000, immutable`` (1 year).
- ``?h=`` absent → ``public, max-age=86400`` (1 day fallback for ad-hoc/dev).

The backend ignores the value of ``h``; it's purely a cache-buster.
"""
import threading

from flask import Blueprint, jsonify, request

from services import audio_fetch, audio_source, cache
from services.data_loader import load_detailed
from config import PEAKS_SCHEMA_VERSION
from services.peaks import (compute_segment_peaks, get_peaks_for_reciter,
                            is_current_schema)
from services.peaks_history import append_peaks_records, load_peaks_records
from utils.decorators import require_edit_lock, require_same_origin
from utils.references import chapter_from_ref

peaks_bp = Blueprint("peaks", __name__, url_prefix="/api/seg")


def _peaks_cache_headers() -> dict[str, str]:
    """Return Cache-Control header dict based on ``?h=`` presence."""
    if request.args.get("h"):
        return {"Cache-Control": "public, max-age=31536000, immutable"}
    return {"Cache-Control": "public, max-age=86400"}


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
    # Filter pre-v2 entries out -- the in-memory cache can still hold them
    # from before a schema bump (long-running process, no restart yet), and
    # the v1 bucketer's stretched timeline would otherwise leak past the
    # invalidations in `read_prefetched_peaks`.
    result = {u: cached[u] for u in target_urls if u in cached and is_current_schema(cached[u])}

    # Short-circuit: if the prefetch worker already wrote peaks JSON to the
    # bucket for any of the remaining URLs, hydrate from there. Misses fall
    # through to the in-memory cache + background compute path below.
    for url in target_urls - result.keys():
        peaks = audio_fetch.read_prefetched_peaks(reciter, url)
        if peaks is not None:
            result[url] = peaks
            with lock:
                cache.set_peaks_for_url(reciter, url, peaks)

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

    response = jsonify({"peaks": result, "complete": complete})
    # Only emit `immutable, max-age=…` when the response is BOTH complete AND
    # non-empty. An empty `complete=true` response (e.g. reciter has no audio
    # URLs at all) under `immutable` would forever poison the cache: peaks
    # that compute later in the background would be invisible. Falling back
    # to `no-store` for the empty-complete case keeps clients honest.
    if complete and result:
        for k, v in _peaks_cache_headers().items():
            response.headers[k] = v
    else:
        response.headers["Cache-Control"] = "no-store"
    return response


@peaks_bp.route("/segment-peaks/<reciter>", methods=["POST"])
def seg_segment_peaks(reciter):
    """Fetch peaks for individual segments.

    Three sources, in order:

    1. Slice the prefetched chapter-peaks JSON if present — free, ~O(N) array
       slice. Honours an optional per-segment ``pad_ms`` so split / auto-split
       scrubbers can show neighbour samples beyond the segment boundary
       (clamped to ``[0, duration_ms]``).
    2. Compute via ffmpeg-on-local-bytes (resolver bucket/disk hit).
    3. HTTP Range decode against the CDN URL (CBR-correct fallback).
    """
    body = request.get_json(silent=True) or {}
    segments = body.get("segments", [])
    cached_only = body.get("cached_only", False)
    results = {}
    chapter_peaks_cache: dict[str, dict | None] = {}

    for seg in segments:
        url = seg.get("url", "")
        start_ms = seg.get("start_ms", 0)
        end_ms = seg.get("end_ms", 0)
        chapter = seg.get("chapter")
        pad_ms = int(seg.get("pad_ms", 0) or 0)
        if not url or end_ms <= start_ms:
            continue
        key = f"{url}:{start_ms}:{end_ms}:{pad_ms}" if pad_ms else f"{url}:{start_ms}:{end_ms}"

        if url not in chapter_peaks_cache:
            chapter_peaks_cache[url] = audio_source.resolve_chapter_peaks(reciter, url)
        chapter_peaks = chapter_peaks_cache[url]
        sliced = _slice_chapter_peaks(chapter_peaks, start_ms, end_ms, pad_ms)
        if sliced is not None:
            results[key] = sliced
            continue

        data = compute_segment_peaks(
            url,
            max(0, start_ms - pad_ms),
            end_ms + pad_ms,
            reciter,
            cached_only=cached_only,
            chapter=chapter,
        )
        if data:
            results[key] = data
    return jsonify({"peaks": results})


def _slice_chapter_peaks(chapter_peaks: dict | None, start_ms: int, end_ms: int,
                         pad_ms: int) -> dict | None:
    """Slice a chapter-peaks dict into a segment window. None when unusable.

    Pad expands on both sides and is clamped to ``[0, duration_ms]`` so the
    scrubber gets context past the segment boundary without falling off the
    end of the chapter.
    """
    if not isinstance(chapter_peaks, dict):
        return None
    peaks = chapter_peaks.get("peaks")
    duration_ms = chapter_peaks.get("duration_ms")
    if not isinstance(peaks, list) or not peaks:
        return None
    if not isinstance(duration_ms, int) or duration_ms <= 0:
        return None

    lo = max(0, start_ms - pad_ms)
    hi = min(duration_ms, end_ms + pad_ms)
    if hi <= lo:
        return None

    n = len(peaks)
    start_idx = max(0, min(n, int(lo * n / duration_ms)))
    end_idx = max(start_idx, min(n, int(round(hi * n / duration_ms))))
    if end_idx == start_idx:
        end_idx = min(n, start_idx + 1)

    return {
        "schema_version": PEAKS_SCHEMA_VERSION,
        "start_ms": lo,
        "end_ms": hi,
        "duration_ms": hi - lo,
        "peaks": peaks[start_idx:end_idx],
    }


@peaks_bp.route("/history-peaks/<reciter>", methods=["GET"])
def seg_history_peaks_get(reciter):
    """Return persisted per-op peaks for the History panel.

    Returns ``{"records": [...]}`` — empty list if the reciter has no
    edit_history_peaks.jsonl yet. The frontend pushes each record into the
    covering-range cache so history rows render without re-computing.

    Mutates on every save; ``no-store`` to keep the History panel honest.
    """
    response = jsonify({"records": load_peaks_records(reciter)})
    response.headers["Cache-Control"] = "no-store"
    return response


@peaks_bp.route("/history-peaks/<reciter>", methods=["POST"])
@require_same_origin
@require_edit_lock(reciter_param="reciter", admin_bypass=True)
def seg_history_peaks_post(reciter):
    """Append peak records computed lazily during History playback.

    Payload: ``{"records": [{op_id, url, start_ms, end_ms, peaks, duration_ms,
    batch_id?}, ...]}``. Used when a History canvas computes peaks on play —
    persisting them here makes future sessions render the same row without a
    Range fetch.

    Gated by ``require_edit_lock`` because this writes
    ``edit_history_peaks.jsonl`` in the bucket — same writer-policy as
    save/undo.
    """
    body = request.get_json(silent=True) or {}
    records = body.get("records", [])
    if not isinstance(records, list):
        return jsonify({"error": "records must be a list"}), 400
    written = append_peaks_records(reciter, records)
    return jsonify({"ok": True, "written": written})
