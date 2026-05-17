"""Waveform peaks routes (/api/seg/peaks).

Cache-Control strategy: peaks are deterministic for a given (reciter, chapter,
segment-range) but the response body changes when a reviewer edits segment
boundaries. The frontend appends ``?h=<hash>`` to peaks URLs computed from
the source content (segment boundaries, audio URL). When the source changes,
the hash changes, which is a fresh cache key.

- ``?h=<sha>`` present → ``public, max-age=31536000, immutable`` (1 year).
- ``?h=`` absent → ``public, max-age=86400`` (1 day fallback for ad-hoc/dev).

The backend ignores the value of ``h``; it's purely a cache-buster.

Performance shape (post slim-peaks migration):

- Peaks files on the bucket are slim packed (``services/audio/peaks_slim.py``,
  ~21 KiB / chapter avg, 40× smaller than the legacy v2 float-JSON).
- The route just reads the requested chapters in parallel (ThreadPool×8) and
  responds. No compute path — files either exist or they don't, and missing
  ones are filled later by the prefetch fallback writer.
- In-memory ``_PEAKS_RESPONSE_CACHE`` (LRU 50) deduplicates repeat identical
  requests; ``invalidate_seg_caches`` evicts on save/undo.
"""
from concurrent.futures import ThreadPoolExecutor

import orjson
from flask import Blueprint, Response, jsonify, request

from config import PEAKS_SCHEMA_VERSION
from services import audio_fetch, audio_source, cache
from services.data_loader import load_detailed
from services.peaks import compute_segment_peaks
from services.peaks_history import append_peaks_records, load_peaks_records
from utils.decorators import require_edit_lock, require_same_origin
from utils.references import chapter_from_ref

peaks_bp = Blueprint("peaks", __name__, url_prefix="/api/seg")

# Bucket read fan-out for multi-chapter requests. Bucket reads release the GIL
# (FUSE I/O), so threads are the right primitive. Worst-case 114-chapter
# request: 114 reads ÷ 8 workers × ~3 ms warm/file ≈ ~45 ms.
_PEAKS_READ_WORKERS = 8


def _peaks_cache_headers() -> dict[str, str]:
    """Return Cache-Control header dict based on ``?h=`` presence."""
    if request.args.get("h"):
        return {"Cache-Control": "public, max-age=31536000, immutable"}
    return {"Cache-Control": "public, max-age=86400"}


@peaks_bp.route("/peaks/<reciter>")
def seg_peaks(reciter):
    """Return pre-computed waveform peaks for a reciter's audio files.

    Reads slim packed peaks (``wip/<slug>/peaks/<chapter>.json.gz``) for
    every URL in the requested chapters, inflated by
    ``audio_fetch.read_prefetched_peaks``. Response shape preserved from the
    pre-migration route -- FE consumers (``_fetchPeaks`` /
    ``setWaveformPeaks``) see the same ``{peaks: {<url>: {...}}, complete}``
    contract.
    """
    entries = load_detailed(reciter)
    if not entries:
        return jsonify({"error": "Reciter not found"}), 404

    chapters_param = request.args.get("chapters", "")
    chapter_filter: set[int] | None = None
    if chapters_param:
        try:
            chapter_filter = {int(c) for c in chapters_param.split(",") if c.strip()}
        except ValueError:
            pass

    # Build the (reciter, sorted_chapter_tuple) cache key. Use the FILTER
    # itself rather than the URL set so cache keys stay compact and stable
    # across detailed.json mutations that don't actually change peaks.
    chapter_key = tuple(sorted(chapter_filter)) if chapter_filter else ()
    cached_bytes = cache.get_peaks_response_cache(reciter, chapter_key)
    if cached_bytes is not None:
        # Skip jsonify entirely — bytes are already serialized JSON ready to
        # send. For the worst chapter (husary ch2, 119k peak tuples) this
        # avoids ~1.5-2s of jsonify CPU per hit. flask-compress still
        # negotiates Content-Encoding per request.
        response = Response(cached_bytes, mimetype="application/json")
        for k, v in _peaks_cache_headers().items():
            response.headers[k] = v
        return response

    target_urls: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        ch = chapter_from_ref(entry["ref"])
        if chapter_filter is not None and ch not in chapter_filter:
            continue
        url = entry.get("audio", "")
        if url and url not in seen:
            seen.add(url)
            target_urls.append(url)

    # In-process per-URL cache (used by ``seg_segment_peaks`` slicer too).
    # Hydrate from it first, then fan-out bucket reads for misses.
    # ``cache.get_peaks_lock()`` is a non-reentrant Lock and ``set_peaks_for_url``
    # takes it internally — so we MUST NOT wrap the set call in another
    # ``with lock`` block (that would deadlock the same thread). The lock
    # bookkeeping lives inside the cache helpers themselves.
    per_url = cache.get_peaks_cache(reciter)
    result: dict[str, dict] = {u: per_url[u] for u in target_urls if u in per_url}

    misses = [u for u in target_urls if u not in result]
    if misses:
        def _read(url: str) -> tuple[str, dict | None]:
            return url, audio_fetch.read_prefetched_peaks(reciter, url)

        with ThreadPoolExecutor(max_workers=_PEAKS_READ_WORKERS) as pool:
            for url, peaks in pool.map(_read, misses):
                if peaks is not None:
                    result[url] = peaks
                    cache.set_peaks_for_url(reciter, url, peaks)

    # ``complete`` is preserved on the wire for FE back-compat, but always
    # True now: there's no background compute path that fills in missing
    # peaks after the fact. A URL missing from ``result`` means its slim
    # file is genuinely absent (chapter wasn't prefetched, or extraction
    # failed for it) and the FE falls through to ``/segment-peaks`` POST
    # per-segment as it does for non-prewarmed reciters today.
    body = {"peaks": result, "complete": True}
    # Serialize once via orjson (~3× faster than stdlib json on big payloads)
    # and cache the bytes so warm requests skip both jsonify and the
    # orjson encode entirely. flask-compress runs on top per-request.
    body_bytes = orjson.dumps(body)
    if result:
        cache.set_peaks_response_cache(reciter, chapter_key, body_bytes)
    response = Response(body_bytes, mimetype="application/json")
    if result:
        for k, v in _peaks_cache_headers().items():
            response.headers[k] = v
    else:
        # Empty response shouldn't poison a long-lived cache; if peaks
        # arrive later via prefetch, the client should retry.
        response.headers["Cache-Control"] = "no-store"
    return response


@peaks_bp.route("/segment-peaks/<reciter>", methods=["POST"])
def seg_segment_peaks(reciter):
    """Fetch peaks for individual segments.

    Two sources, in order:

    1. Slice the prefetched chapter-peaks JSON if present — free, ~O(N) array
       slice. Honours an optional per-segment ``pad_ms`` so split / auto-split
       scrubbers can show neighbour samples beyond the segment boundary
       (clamped to ``[0, duration_ms]``).
    2. ffmpeg-decode the segment via ``compute_segment_peaks`` — no caching,
       per request. ``cached_only=true`` in the body skips this fallback so
       the client gets only bucket-resident peaks.
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

        if cached_only:
            continue

        data = compute_segment_peaks(
            url,
            max(0, start_ms - pad_ms),
            end_ms + pad_ms,
            reciter,
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
