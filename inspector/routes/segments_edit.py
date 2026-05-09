"""Segments tab edit routes (/api/seg/ — save, undo)."""
from flask import Blueprint, jsonify, request

from services.save import save_seg_data as _save_seg_data
from services.undo import undo_batch as _undo_batch, undo_ops as _undo_ops

seg_edit_bp = Blueprint("seg_edit", __name__, url_prefix="/api/seg")


@seg_edit_bp.route("/save/<reciter>/<int:chapter>", methods=["POST"])
def seg_save(reciter, chapter):
    """Save edited segments back to detailed.json and segments.json."""
    updates = request.get_json()
    if not updates or "segments" not in updates:
        return jsonify({"error": "Missing segments in request body"}), 400
    result = _save_seg_data(reciter, chapter, updates)
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@seg_edit_bp.route("/undo-batch/<reciter>", methods=["POST"])
def seg_undo_batch(reciter):
    """Undo a specific saved batch by reversing its operations."""
    body = request.get_json()
    if not body or not body.get("batch_id"):
        return jsonify({"error": "Missing batch_id"}), 400
    result = _undo_batch(reciter, body["batch_id"])
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@seg_edit_bp.route("/undo-ops/<reciter>", methods=["POST"])
def seg_undo_ops(reciter):
    """Undo specific operations within a saved batch."""
    body = request.get_json()
    if not body or not body.get("batch_id") or not body.get("op_ids"):
        return jsonify({"error": "Missing batch_id or op_ids"}), 400
    result = _undo_ops(reciter, body["batch_id"], set(body["op_ids"]))
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)
