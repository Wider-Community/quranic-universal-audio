"""Audio proxy route (``/api/seg/audio-proxy``).

Single GET route. Lookup order:

1. **Bucket-resident audio** — ``wip/<slug>/audio/<chapter>.mp3`` written
   by the katana extraction pipeline (`.local/extraction/upload_to_bucket.py`).
   Served via ``send_file`` (uses OS sendfile, honours Range + 304). The
   ``-c:a copy -f mp3`` step in ``audio_persist.py`` injects an Xing/Info
   header so the browser computes ``<audio>.duration`` correctly.
2. **CDN stream-through** — for slugs the extraction pipeline hasn't
   reached yet (anonymous browsing, pre-extraction onboarding, by_ayah
   deliveries). We stream the upstream response through Flask instead of
   302-redirecting so the bytes always arrive same-origin from the
   browser's perspective with explicit CORS headers. The naive 302 fails
   for ``<audio crossorigin="anonymous">``: the redirect response itself
   carries no ``Access-Control-Allow-Origin`` header, so even though
   every published-reciter CDN sends ACAO on the final response, the
   redirect chain is treated as opaque by Chrome's Fetch impl and
   ``MediaElementAudioSourceNode`` produces silence.

The download-all + delete-cache + cache-status endpoints have been removed
— bucket audio is populated by the offline pipeline, not by a Space-side
warm path. The 1-week post-RELEASED GC lives in
``services.audio_prefetch.sweep_due`` (see
``docs/reference/inspector/wip-audio-sweeper.md``).
"""

import logging
from io import BytesIO

import requests
from flask import Blueprint, Response, jsonify, request, send_file, stream_with_context

from config import AUDIO_CACHE_MAX_AGE, AUDIO_MIME_TYPES
from services import audio_source

logger = logging.getLogger(__name__)

audio_proxy_bp = Blueprint("audio_proxy", __name__, url_prefix="/api/seg")

# Stream the CDN response through Flask in 64 KB chunks. Matches the
# Range-fetch granularity browsers use for `<audio>` scrubbing.
_STREAM_CHUNK_BYTES = 64 * 1024
# Cap a single upstream fetch at 30 s — covers cold CDN edge nodes without
# letting a hung connection block the single Flask worker indefinitely.
_UPSTREAM_TIMEOUT_SECS = 30


def _stream_cdn(url: str) -> Response:
    """Pull *url* from the CDN and stream it back to the caller as a
    same-origin response with explicit CORS headers. Forwards the browser's
    ``Range`` header so partial-content requests stay byte-range accurate.

    Why same-origin matters: ``<audio crossorigin="anonymous">`` paired with
    the Web Audio kill-switch (``MediaElementAudioSourceNode``) silences
    the audio if any link in the request chain has missing/invalid CORS
    headers. Flask's ``redirect(url, 302)`` adds no ACAO, so the chain
    breaks even when the final CDN response sends ``ACAO: *``. Streaming
    keeps the response same-origin and we attach ACAO ourselves.

    This branch dies the day every reciter has bucket-cached audio (see
    module docstring).
    """
    req_headers = {"User-Agent": "Mozilla/5.0"}
    if rng := request.headers.get("Range"):
        req_headers["Range"] = rng
    try:
        upstream = requests.get(
            url, headers=req_headers, stream=True, timeout=_UPSTREAM_TIMEOUT_SECS,
        )
    except requests.RequestException as exc:
        logger.warning("audio_proxy: upstream fetch failed url=%s err=%s", url, exc)
        return jsonify({"error": "upstream audio fetch failed"}), 502

    immutable = f"public, max-age={AUDIO_CACHE_MAX_AGE}, immutable"
    out_headers = {
        "Content-Type": upstream.headers.get("Content-Type", "audio/mpeg"),
        "Accept-Ranges": "bytes",
        "Cache-Control": immutable,
        "Access-Control-Allow-Origin": "*",
    }
    # Forward Content-Length / Content-Range so the browser knows the
    # response size and which byte slice it just got (Werkzeug fills these
    # automatically only on local-file send_file paths).
    for h in ("Content-Length", "Content-Range"):
        if h in upstream.headers:
            out_headers[h] = upstream.headers[h]

    def _stream():
        try:
            for chunk in upstream.iter_content(_STREAM_CHUNK_BYTES):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return Response(
        stream_with_context(_stream()),
        status=upstream.status_code,
        headers=out_headers,
    )


@audio_proxy_bp.route("/audio-proxy/<reciter>")
def seg_audio_proxy(reciter):
    """Proxy/serve a chapter MP3 via the shared audio-source resolver.

    Priority: mount/disk path (streamed via send_file with Range + ETag/304)
    → in-memory bytes (local-dev fallback, still served with Range via a
    seekable BytesIO) → CDN stream-through (legacy reciters without
    bucket-cached audio). Browser issues partial-content requests once the
    first response advertises ``Accept-Ranges``; subsequent seeks are
    byte-range fetches handled by Werkzeug's conditional path (local) or
    re-streamed through ``_stream_cdn`` with a fresh ``Range`` header.
    """
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "No url provided"}), 400

    src = audio_source.resolve(reciter, url)
    immutable = f"public, max-age={AUDIO_CACHE_MAX_AGE}, immutable"

    if src.path is not None:
        mime = AUDIO_MIME_TYPES.get(src.path.suffix.lower(), "audio/mpeg")
        resp = send_file(
            src.path,
            mimetype=mime,
            conditional=True,
            etag=True,
            last_modified=src.path.stat().st_mtime,
            max_age=AUDIO_CACHE_MAX_AGE,
        )
        resp.headers["Cache-Control"] = immutable
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp

    if src.data is not None:
        resp = send_file(
            BytesIO(src.data),
            mimetype="audio/mpeg",
            conditional=True,
            etag=f"{src.chapter_key or 'chapter'}-{len(src.data)}",
        )
        resp.headers["Cache-Control"] = immutable
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp

    return _stream_cdn(url)
