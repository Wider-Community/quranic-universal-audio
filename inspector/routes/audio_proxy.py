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

from io import BytesIO

from flask import Blueprint, jsonify, redirect, request, send_file

from config import AUDIO_CACHE_MAX_AGE, AUDIO_MIME_TYPES
from services import audio_source

audio_proxy_bp = Blueprint("audio_proxy", __name__, url_prefix="/api/seg")


@audio_proxy_bp.route("/audio-proxy/<reciter>")
def seg_audio_proxy(reciter):
    """Proxy/serve a chapter MP3 via the shared audio-source resolver:
    bucket-prefetched bytes → local disk cache → 302 to CDN."""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "No url provided"}), 400

    src = audio_source.resolve(reciter, url)
    immutable = f"public, max-age={AUDIO_CACHE_MAX_AGE}, immutable"

    if src.data is not None:
        resp = send_file(BytesIO(src.data), mimetype="audio/mpeg")
        resp.headers["Cache-Control"] = immutable
        return resp

    if src.path is not None:
        mime = AUDIO_MIME_TYPES.get(src.path.suffix.lower(), "audio/mpeg")
        resp = send_file(src.path, mimetype=mime)
        resp.headers["Cache-Control"] = immutable
        return resp

    return redirect(url, 302)
