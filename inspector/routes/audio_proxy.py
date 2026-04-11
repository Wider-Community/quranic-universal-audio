"""Audio proxy/cache routes (/api/seg/audio-proxy, audio-cache, etc.)."""
import concurrent.futures
import threading

from flask import Blueprint, jsonify, request, send_file

from config import AUDIO_CACHE_MAX_AGE, AUDIO_MIME_TYPES
from services import cache
from services.audio_proxy import delete_audio_cache, download_audio, scan_audio_cache
from services.data_loader import load_detailed
from utils.references import chapter_from_ref

audio_proxy_bp = Blueprint("audio_proxy", __name__, url_prefix="/api/seg")


@audio_proxy_bp.route("/audio-proxy/<reciter>")
def seg_audio_proxy(reciter):
    """Proxy and cache audio from CDN."""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "No url provided"}), 400
    cache_path = cache.audio_cache_path(reciter, url)
    if not cache_path.exists():
        result = download_audio(reciter, url)
        if not result:
            return jsonify({"error": "Download failed"}), 502
    mime = AUDIO_MIME_TYPES.get(cache_path.suffix.lower(), "audio/mpeg")
    resp = send_file(cache_path, mimetype=mime)
    resp.headers["Cache-Control"] = f"public, max-age={AUDIO_CACHE_MAX_AGE}, immutable"
    return resp


@audio_proxy_bp.route("/audio-cache-status/<reciter>")
def seg_audio_cache_status(reciter):
    """Return cache status for a reciter's audio files."""
    status = scan_audio_cache(reciter)
    if status["total"] == 0:
        return jsonify({"error": "Reciter not found"}), 404
    progress = cache.get_audio_dl_progress(reciter)
    return jsonify({
        **status,
        "downloading": progress and not progress.get("complete", False),
        "download_progress": progress,
    })


@audio_proxy_bp.route("/prepare-audio/<reciter>", methods=["POST"])
def seg_prepare_audio(reciter):
    """Start background download of all audio for a reciter."""
    entries = load_detailed(reciter)
    if not entries:
        return jsonify({"error": "Reciter not found"}), 404
    urls = {}
    for entry in entries:
        ch = chapter_from_ref(entry["ref"])
        url = entry.get("audio", "")
        if url and str(ch) not in urls:
            urls[str(ch)] = url
    to_download = {ch: u for ch, u in urls.items() if not cache.audio_cache_path(reciter, u).exists()}
    total = len(urls)
    already_cached = total - len(to_download)

    dl_lock = cache.get_audio_dl_lock()
    with dl_lock:
        existing = cache.get_audio_dl_progress(reciter)
        if existing and not existing.get("complete", False):
            return jsonify({"status": "already_running", **existing})
        cache.set_audio_dl_progress(reciter, {
            "total": total, "downloaded": already_cached, "complete": False
        })

    def _bg():
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(download_audio, reciter, u): ch for ch, u in to_download.items()}
            for future in concurrent.futures.as_completed(futures):
                with dl_lock:
                    prog = cache.get_audio_dl_progress(reciter)
                    if prog:
                        prog["downloaded"] = prog["downloaded"] + 1
            with dl_lock:
                prog = cache.get_audio_dl_progress(reciter)
                if prog:
                    prog["complete"] = True
            cache.pop_audio_cache_status(reciter)

    threading.Thread(target=_bg, daemon=True).start()
    return jsonify({"status": "started", "total": total, "to_download": len(to_download)})


@audio_proxy_bp.route("/delete-audio-cache/<reciter>", methods=["DELETE"])
def seg_delete_audio_cache(reciter):
    """Delete all cached data (audio + peaks) for a reciter."""
    result = delete_audio_cache(reciter)
    return jsonify(result)
