"""Segments tab validation, stats, and edit-history routes (/api/seg/)."""
import threading

from flask import Blueprint, jsonify, request

from config import RECITATION_SEGMENTS_PATH
from services.history_query import load_edit_history
from utils.io import safe_filename
from services.stats import compute_stats
from services.validation import run_validation_log, validate_reciter_segments

seg_val_bp = Blueprint("seg_val", __name__, url_prefix="/api/seg")


@seg_val_bp.route("/trigger-validation/<reciter>", methods=["POST"])
def seg_trigger_validation(reciter):
    """Kick off validation.log generation in background."""
    threading.Thread(
        target=lambda: run_validation_log(RECITATION_SEGMENTS_PATH / reciter),
        daemon=True,
    ).start()
    return jsonify({"ok": True})


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


@seg_val_bp.route("/stats/<reciter>/save-chart", methods=["POST"])
def seg_save_chart(reciter):
    """Save a chart PNG to data/recitation_segments/<reciter>/analysis/."""
    seg_dir = RECITATION_SEGMENTS_PATH / reciter
    if not seg_dir.exists():
        return jsonify({"error": "Reciter not found"}), 404
    name = safe_filename(request.form.get("name", "chart"), fallback="chart")
    f = request.files.get("image")
    if not f:
        return jsonify({"error": "No image provided"}), 400
    out_dir = seg_dir / "analysis"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{name}.png"
    f.save(str(out_path))
    return jsonify({"ok": True, "path": str(out_path)})


@seg_val_bp.route("/edit-history/<reciter>")
def seg_edit_history(reciter):
    """Return edit history batches and summary stats for the reciter."""
    return jsonify(load_edit_history(reciter))
