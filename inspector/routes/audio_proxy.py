"""Audio proxy route (``/api/seg/audio-proxy``).

Single GET route. Lookup order:

1. **Bucket prefetch** — ``wip/<slug>/audio/<chapter>.mp3`` written by
   ``services.audio_prefetch`` when the row enters AWAITING_REVIEW. VBR
   chapters have a Xing TOC injected at prefetch time, so direct
   ``<audio>.currentTime`` seek works without the clip-route.
2. **Legacy local disk cache** — ``CACHE_DIR/<reciter>/audio/<urlhash>.mp3``
   from the old prepare-audio button. Kept as a second tier until those
   files age out organically.
3. **CDN redirect (302)** — for slugs the prefetch hasn't reached yet
   (anonymous browsing, in-flight prefetch, by_ayah deliveries we don't
   prefetch today).

The download-all + delete-cache + cache-status endpoints have been removed
— the prefetch is event-driven now, not user-driven. Admin re-trigger lives
under ``/api/admin/prefetch-rerun/<slug>``.
"""

from flask import Blueprint, jsonify, redirect, request, send_file

from config import AUDIO_CACHE_MAX_AGE, AUDIO_MIME_TYPES
from services import audio_fetch, cache

audio_proxy_bp = Blueprint("audio_proxy", __name__, url_prefix="/api/seg")


@audio_proxy_bp.route("/audio-proxy/<reciter>")
def seg_audio_proxy(reciter):
    """Proxy/serve a chapter MP3 — bucket prefetch first, local cache second,
    CDN redirect last."""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "No url provided"}), 400

    # Tier 1 — bucket prefetch.
    data = audio_fetch.read_prefetched_audio_bytes(reciter, url)
    if data is not None:
        from io import BytesIO

        resp = send_file(BytesIO(data), mimetype="audio/mpeg")
        resp.headers["Cache-Control"] = (
            f"public, max-age={AUDIO_CACHE_MAX_AGE}, immutable"
        )
        return resp

    # Tier 2 — legacy local disk cache (pre-prefetch deployments).
    cache_path = cache.audio_cache_path(reciter, url)
    if cache_path.exists():
        mime = AUDIO_MIME_TYPES.get(cache_path.suffix.lower(), "audio/mpeg")
        resp = send_file(cache_path, mimetype=mime)
        resp.headers["Cache-Control"] = (
            f"public, max-age={AUDIO_CACHE_MAX_AGE}, immutable"
        )
        return resp

    # Tier 3 — CDN fallback.
    return redirect(url, 302)
