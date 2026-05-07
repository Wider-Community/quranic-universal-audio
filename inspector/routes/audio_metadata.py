"""Audio tab metadata routes (/api/audio/*)."""
import json

from flask import Blueprint, jsonify

from config import AUDIO_METADATA_PATH
from services import cache
from services.data_loader import load_audio_sources

audio_meta_bp = Blueprint("audio_meta", __name__, url_prefix="/api/audio")


@audio_meta_bp.route("/sources")
def audio_sources():
    """Return hierarchical audio source structure."""
    return jsonify(load_audio_sources())


@audio_meta_bp.route("/surahs/<category>/<source>/<slug>")
def audio_surahs(category, source, slug):
    """Return surah/ayah URLs for a reciter within a specific source."""
    key = f"{category}/{source}/{slug}"
    cached = cache.get_audio_url_cache(key)
    if cached is not None:
        return jsonify({"surahs": cached})
    path = AUDIO_METADATA_PATH / category / source / f"{slug}.json"
    if not path.exists():
        return jsonify({"error": "Reciter not found"}), 404
    with open(path, encoding="utf-8") as f:
        surahs = json.load(f)
    surahs.pop("_meta", None)
    surahs = {k: (v["url"] if isinstance(v, dict) else v) for k, v in surahs.items()}
    cache.set_audio_url_cache(key, surahs)
    return jsonify({"surahs": surahs})
