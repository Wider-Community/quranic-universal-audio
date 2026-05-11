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
    """Return surah/ayah URLs for a reciter within a specific source.

    v2: reads the per-delivery audio_manifest sidecar from
    ``<bucket>/catalog/audio_manifest/<slug>.json``. Phase 1's stub catalog
    hasn't promoted sidecars yet, so this route returns 404 for every slug
    until the bulk audio probe completes and ``seed_catalog_stub`` is
    extended (Phase 6 work).
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
    surahs = {k: (v.get("url") if isinstance(v, dict) else v) for k, v in chapters.items()}
    cache.set_audio_url_cache(key, surahs)
    return jsonify({"surahs": surahs})
