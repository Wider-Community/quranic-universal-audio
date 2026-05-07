"""Segments tab edit routes (/api/seg/ — save, undo, resolve_ref)."""
from flask import Blueprint, jsonify, request

from services.data_loader import dk_text_for_ref
from services.phonemizer_service import get_phonemizer, has_phonemizer
from services.save import save_seg_data as _save_seg_data
from services.undo import undo_batch as _undo_batch, undo_ops as _undo_ops

seg_edit_bp = Blueprint("seg_edit", __name__, url_prefix="/api/seg")


@seg_edit_bp.route("/resolve_ref")
def seg_resolve_ref():
    """Resolve a word-range reference to its Arabic text via the phonemizer."""
    ref = request.args.get("ref", "").strip()
    if not ref:
        return jsonify({"error": "No ref provided"}), 400
    if not has_phonemizer():
        return jsonify({"error": "Phonemizer not available"}), 503
    try:
        pm = get_phonemizer()
        result = pm.phonemize(ref=ref)
        mapping = result.get_mapping()
        text = " ".join(w.text for w in mapping.words)
        display_text = dk_text_for_ref(ref)
        return jsonify({"text": text, "display_text": display_text or text})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


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
