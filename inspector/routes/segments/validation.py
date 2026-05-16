"""Segments tab validation, stats, and edit-history routes (/api/seg/)."""

from flask import Blueprint, jsonify

from services import cache
from services.history_query import load_edit_history
from services.stats import compute_stats
from services.validation import validate_reciter_segments
from utils.json_response import orjson_cached_response

seg_val_bp = Blueprint("seg_val", __name__, url_prefix="/api/seg")


@seg_val_bp.route("/validate/<reciter>")
def seg_validate(reciter):
    """Validate all chapters for a reciter (cached; invalidated on save)."""
    cached = cache.get_seg_validate_cache(reciter)
    if cached is not None:
        return orjson_cached_response(cached)
    result = validate_reciter_segments(reciter)
    if result is None:
        return jsonify({"error": "Reciter not found"}), 404
    cache.set_seg_validate_cache(reciter, result)
    return orjson_cached_response(result)


@seg_val_bp.route("/stats/<reciter>")
def seg_stats(reciter):
    """Return segmentation statistics and histogram distributions (cached)."""
    cached = cache.get_seg_stats_cache(reciter)
    if cached is not None:
        return orjson_cached_response(cached)
    result = compute_stats(reciter)
    if result is None:
        return jsonify({"error": "Reciter not found"}), 404
    cache.set_seg_stats_cache(reciter, result)
    return orjson_cached_response(result)


# v2: `seg_save_chart` removed — debug-only route with no UI surface.
# See inspector-cleanup-registry.md §2.


@seg_val_bp.route("/edit-history/<reciter>")
def seg_edit_history(reciter):
    """Return edit history batches and summary stats for the reciter."""
    return orjson_cached_response(load_edit_history(reciter))
