"""Audio tab metadata routes (/api/audio/*)."""

from flask import Blueprint, jsonify

from services import cache, storage_paths
from services.data_loader import load_audio_sources
from services.hf_bucket import StorageNotFound, get_backend

audio_meta_bp = Blueprint("audio_meta", __name__, url_prefix="/api/audio")


@audio_meta_bp.route("/sources")
def audio_sources():
    """Return hierarchical audio source structure (built from the catalog)."""
    return jsonify(load_audio_sources())


@audio_meta_bp.route("/surahs/<category>/<source>/<slug>")
def audio_surahs(category, source, slug):
    """Return per-chapter ``{url, duration_ms}`` for a delivery.

    Reads the per-delivery audio_manifest sidecar from
    ``<bucket>/catalog/audio_manifest/<slug>.json``. ``duration_ms`` is
    derived from the sidecar's ``duration_sec`` so the dashboard player can
    show full chapter length before the browser fetches MP3 headers — the
    ``BottomPlayer`` runs ``<audio preload="none">`` and would otherwise
    show ``0:00`` until first play.
    """
    key = f"{category}/{source}/{slug}"
    cached = cache.get_audio_url_cache(key)
    if cached is not None:
        return jsonify({"surahs": cached})
    try:
        doc = get_backend().read_json(storage_paths.audio_manifest_path(slug))
    except StorageNotFound:
        return jsonify({"error": "Reciter not found"}), 404
    if not isinstance(doc, dict):
        return jsonify({"error": "invalid audio_manifest sidecar"}), 500
    chapters = doc.get("chapters") or {}
    surahs: dict[str, dict] = {}
    for k, v in chapters.items():
        if isinstance(v, dict):
            url = v.get("url")
            if not isinstance(url, str):
                continue
            duration_sec = v.get("duration_sec")
            duration_ms = (
                int(round(duration_sec * 1000))
                if isinstance(duration_sec, (int, float))
                else None
            )
            surahs[k] = {"url": url, "duration_ms": duration_ms}
        elif isinstance(v, str):
            surahs[k] = {"url": v, "duration_ms": None}
    cache.set_audio_url_cache(key, surahs)
    return jsonify({"surahs": surahs})
