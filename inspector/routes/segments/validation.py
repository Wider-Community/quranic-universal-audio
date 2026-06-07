"""Segments tab validation, stats, and edit-history routes (/api/seg/)."""

from flask import Blueprint, jsonify

from services import cache
from services.history_query import load_edit_history
from services.segments.history_tiers import generation_timeline
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
    """Return edit history batches, summary stats, and the TS-generation timeline.

    ``generations`` (the per-generation boundary list) is computed fresh from the
    release tables on each call and merged onto the cached ``{batches, summary}``
    blob — so the heavy edit-history parse stays cached while the boundary list
    stays current after a regeneration without an explicit cache bust.
    """
    history = load_edit_history(reciter)
    payload = {**history, "generations": generation_timeline(reciter)}
    return orjson_cached_response(payload)
