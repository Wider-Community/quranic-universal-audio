"""Waveform peaks routes (``/api/seg/peaks`` + ``/api/seg/segment-peaks`` +
``/api/seg/history-peaks``).

Two-tier shape (see ``the inspector-audio skill``):

1. **Chapter-overview peaks** — ``GET /api/seg/peaks/<reciter>?chapters=...``.
   Reads the slim packed files from ``<wip|published>/<slug>/peaks/<ch>.json.gz``
   verbatim (no dequant, no ``.tolist()``) and emits ``{q:'int8', n,
   peaks_b64, bps, duration_ms}`` per audio URL. FE holds these as
   ``Int8Array`` end-to-end and slices client-side for each card.

2. **Per-segment ffmpeg fallback** — ``POST /api/seg/segment-peaks/<reciter>``.
   Single fallback tier for the case where a card's chapter peaks aren't
   loaded FE-side (rare on prewarmed reciters once accordion-prefetch ran).
   Decodes via HTTP Range + ffmpeg and returns a nested ``PeakBucket[]``
   slice at the HD 30 bps density.

Cache-Control: ``?h=<hash>`` is a FE-computed cache-buster over the audio URLs
the response will key on. Backend ignores the value; presence flips the
cache directive from ``public, max-age=86400`` (1 day) to
``public, max-age=31536000, immutable`` (1 year) since the hash changes
whenever the underlying audio source flips.
"""

from concurrent.futures import ThreadPoolExecutor

import orjson
from flask import Blueprint, Response, jsonify, request
from pydantic import ValidationError

from qua_shared.schemas.wire._envelopes import ErrorEnvelope
from qua_shared.schemas.wire.seg import (
    SegPeaksResponse,
    SegSegmentPeaksRequestItem,
    SegSegmentPeaksResponse,
)
from services import audio_fetch, cache
from services.audio.audio_meta import chapter_urls
from services.data_loader import load_detailed
from services.history_query import edit_history_op_ids
from services.peaks import compute_segment_peaks
from services.peaks_history import append_peaks_records, load_peaks_records
from utils.decorators import require_same_origin

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
    """Return slim-int8 chapter-overview peaks for ``?chapters=<csv>``.

    Reads ``<wip|published>/<slug>/peaks/<ch>.json.gz`` via
    ``audio_fetch.read_prefetched_peaks`` (raw envelope — no dequant) and
    emits ``{peaks: {<url>: {q:'int8', n, peaks_b64, bps, duration_ms}},
    complete: true}``. ``complete`` is preserved on the wire for FE forward
    compat but always true: this route has no background-compute path.

    Missing chapter files (extraction didn't bake peaks for that chapter,
    or backfill not yet run) simply drop out of the response — FE falls
    through to ``/segment-peaks`` POST per-card as a single fallback tier.
    """
    entries = load_detailed(reciter)
    if not entries:
        return jsonify(ErrorEnvelope(error="Reciter not found").model_dump(exclude_none=True)), 404

    chapters_param = request.args.get("chapters", "")
    chapter_filter: set[int] | None = None
    if chapters_param:
        try:
            chapter_filter = {int(c) for c in chapters_param.split(",") if c.strip()}
        except ValueError:
            pass

    # Cache key uses the FILTER itself rather than the URL set so keys stay
    # compact and stable across detailed.json mutations that don't change
    # peaks. LRU-50 cap and ``invalidate_seg_caches`` policy in cache.py.
    chapter_key = tuple(sorted(chapter_filter)) if chapter_filter else ()
    cached_bytes = cache.get_peaks_response_cache(reciter, chapter_key)
    if cached_bytes is not None:
        # Cached bytes are already serialized JSON — skip jsonify entirely.
        # flask-compress still negotiates Content-Encoding per request.
        response = Response(cached_bytes, mimetype="application/json")
        for k, v in _peaks_cache_headers().items():
            response.headers[k] = v
        return response

    # Migration #5: per-entry ``audio`` field is no longer written by the
    # extractor (post-migration buckets have ``entry.audio == ""`` for every
    # entry → empty ``target_urls`` → empty peaks response). The canonical
    # chapter→URL map lives in ``catalog/audio_manifest/<slug>.json`` and is
    # cached in ``audio_meta._SIDECAR_CACHE`` after the first read by any
    # route. Iterate the sidecar directly; ``key`` is ``"1"``..``"114"`` for
    # by_surah and ``"<surah>:<ayah>"`` for by_ayah deliveries.
    target_urls: list[str] = []
    seen: set[str] = set()
    for key, url in chapter_urls(reciter).items():
        try:
            ch = int(key.split(":", 1)[0])
        except (ValueError, AttributeError):
            continue
        if chapter_filter is not None and ch not in chapter_filter:
            continue
        if url and url not in seen:
            seen.add(url)
            target_urls.append(url)

    # In-process per-URL cache. Hydrate from it first, then fan-out bucket
    # reads for misses. ``cache.set_peaks_for_url`` takes
    # ``cache.get_peaks_lock()`` internally — the route MUST NOT wrap it in
    # another ``with lock`` block (threading.Lock is non-reentrant → deadlock).
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

    body = SegPeaksResponse.model_validate({"peaks": result, "complete": True}).model_dump(
        mode="json", exclude_none=True, by_alias=True
    )
    # Serialize once via orjson (~3× faster than stdlib on big payloads) and
    # cache the bytes so warm requests skip both jsonify and orjson encode.
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
    """Compute per-segment peaks via ffmpeg + HTTP Range.

    Single fallback tier when a card's chapter peaks weren't loaded FE-side
    (chapter-overview peaks are the fast path and the FE slices them
    locally). No server-side caching — each request decodes fresh. Returns
    ``{peaks: {"<url>:<start>:<end>": {peaks, start_ms, end_ms, duration_ms}}}``
    with nested ``PeakBucket[]`` floats at HD 30 bps. ``pad_ms`` widens the
    decoded range symmetrically for split/scrubber UIs.
    """
    # Validate per-item so one malformed slice is skipped, not the whole
    # batch — a bad item shouldn't drop the fallback render for its siblings.
    raw = request.get_json(silent=True) or {}
    raw_items = raw.get("segments", []) if isinstance(raw, dict) else []
    segments = []
    for item in raw_items if isinstance(raw_items, list) else []:
        try:
            segments.append(SegSegmentPeaksRequestItem.model_validate(item))
        except ValidationError:
            continue

    results: dict[str, dict] = {}
    for seg in segments:
        url = seg.url
        start_ms = seg.start_ms
        end_ms = seg.end_ms
        pad_ms = int(seg.pad_ms or 0)
        bps = seg.bps  # History passes 10; default (None) → HD 30 bps
        if not url or end_ms <= start_ms:
            continue
        key = f"{url}:{start_ms}:{end_ms}:{pad_ms}" if pad_ms else f"{url}:{start_ms}:{end_ms}"
        data = compute_segment_peaks(
            url,
            max(0, start_ms - pad_ms),
            end_ms + pad_ms,
            reciter,
            chapter=seg.chapter,
            bps=bps if isinstance(bps, int) else None,
        )
        if data:
            results[key] = data

    body = SegSegmentPeaksResponse.model_validate({"peaks": results}).model_dump(
        mode="json", exclude_none=True, by_alias=True
    )
    return jsonify(body)


# Caps for the on-play write-back POST (any same-origin viewer can call it).
_HISTORY_POST_MAX_RECORDS = 64
_HISTORY_POST_MAX_B64 = 64 * 1024  # one record's peaks_b64; 10 bps × long op ≪ this


@peaks_bp.route("/history-peaks/<reciter>", methods=["GET"])
def seg_history_peaks_get(reciter):
    """Return persisted per-op peaks for the History panel.

    Emits the canonical slim records verbatim — ``{"records": [{op_id, url,
    start_ms, end_ms, bps, peaks_b64}, ...]}`` — no float inflation. The FE
    decodes ``peaks_b64`` → ``Int8Array`` once and indexes by covering range.
    Empty list when the reciter has no ``edit_history_peaks.jsonl`` yet.

    Serialized bytes are cached per reciter (``orjson``) and reused on repeat
    opens — History is browsed heavily, incl. anonymous. Invalidated whenever
    the JSONL is appended (save invalidation + write-back). ``no-store`` on the
    wire so a stale browser copy never masks a freshly-persisted op.
    """
    cached = cache.get_seg_history_peaks_response(reciter)
    if cached is None:
        cached = orjson.dumps({"records": load_peaks_records(reciter)})
        cache.set_seg_history_peaks_response(reciter, cached)
    response = Response(cached, mimetype="application/json")
    response.headers["Cache-Control"] = "no-store"
    return response


@peaks_bp.route("/history-peaks/<reciter>", methods=["POST"])
@require_same_origin
def seg_history_peaks_post(reciter):
    """Persist a peak record computed lazily during History playback.

    Payload: ``{"records": [{op_id, url, start_ms, end_ms, bps, peaks_b64}]}``.
    When a History row has no persisted peaks, it ffmpeg-computes on play (at
    10 bps) and posts the result here so future viewers — including anonymous
    ones — render it instantly.

    **Not** lock-gated: this writes only derived, idempotent peaks for ops that
    already exist, not user edits. Guards instead:
      - ``require_same_origin`` (CSRF),
      - every ``op_id`` must exist in the reciter's edit history,
      - ``append_peaks_records`` dedups by op_id (one record per op),
      - record count + ``peaks_b64`` size are bounded.
    """
    body = request.get_json(silent=True) or {}
    records = body.get("records", [])
    if not isinstance(records, list):
        return jsonify(
            ErrorEnvelope(error="records must be a list").model_dump(exclude_none=True)
        ), 400
    if len(records) > _HISTORY_POST_MAX_RECORDS:
        return jsonify(ErrorEnvelope(error="too many records").model_dump(exclude_none=True)), 413

    valid_op_ids = edit_history_op_ids(reciter)
    accepted: list[dict] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if rec.get("op_id") not in valid_op_ids:
            continue  # unknown op — refuse to persist arbitrary data
        b64 = rec.get("peaks_b64")
        if not isinstance(b64, str) or len(b64) > _HISTORY_POST_MAX_B64:
            continue
        accepted.append(rec)

    written = append_peaks_records(reciter, accepted)
    return jsonify({"ok": True, "written": written, "skipped": len(records) - written})
