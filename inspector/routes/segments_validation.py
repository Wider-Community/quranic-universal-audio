"""Segments tab validation, stats, and edit-history routes (/api/seg/)."""

from flask import Blueprint, jsonify

from services.history_query import load_edit_history
from services.stats import compute_stats
from services.validation import validate_reciter_segments

seg_val_bp = Blueprint("seg_val", __name__, url_prefix="/api/seg")


# v2: `seg_trigger_validation` deprecated — validators run as libraries
# called from `inspector/services/save.py` on every relevant write (Phase 5
# wiring). The route returns 410 Gone until the validator library split
# lands (Phase 6). The frontend's "trigger validation" button is hidden in
# deployed mode anyway.
@seg_val_bp.route("/trigger-validation/<reciter>", methods=["POST"])
def seg_trigger_validation(reciter):
    """Deprecated in v2 — validators are libraries called from the save flow."""
    return jsonify({
        "error": (
            "trigger-validation is deprecated in v2. Validators run as "
            "libraries from inspector/services/save.py on every save."
        )
    }), 410


@seg_val_bp.route("/validate/<reciter>")
def seg_validate(reciter):
    """Validate all chapters for a reciter."""
    result = validate_reciter_segments(reciter)
    if result is None:
        return jsonify({"error": "Reciter not found"}), 404
    return jsonify(result)


@seg_val_bp.route("/stats/<reciter>")
def seg_stats(reciter):
    """Return segmentation statistics and histogram distributions."""
    result = compute_stats(reciter)
    if result is None:
        return jsonify({"error": "Reciter not found"}), 404
    return jsonify(result)


# v2: `seg_save_chart` removed — debug-only route with no UI surface.
# See inspector-cleanup-registry.md §2.


@seg_val_bp.route("/edit-history/<reciter>")
def seg_edit_history(reciter):
    """Return edit history batches and summary stats for the reciter."""
    return jsonify(load_edit_history(reciter))
