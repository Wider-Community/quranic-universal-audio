"""Segments tab validation, stats, and edit-history routes (/api/seg/)."""
import json
import threading
from collections import Counter

from flask import Blueprint, jsonify, request

from config import RECITATION_SEGMENTS_PATH
from services.data_loader import load_detailed
from services.stats import compute_stats
from services.validation import run_validation_log, validate_reciter_segments
from utils.references import chapter_from_ref

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
    name = request.form.get("name", "chart")
    name = "".join(c for c in name if c.isalnum() or c in "-_").strip() or "chart"
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
    history_path = RECITATION_SEGMENTS_PATH / reciter / "edit_history.jsonl"
    if not history_path.exists():
        return jsonify({"batches": [], "summary": None})

    # Parse all records
    all_records = []
    fully_reverted_ids: set[str] = set()
    per_op_reverted: dict[str, set[str]] = {}
    for line in history_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("record_type") == "genesis":
            continue
        all_records.append(record)
        rbid = record.get("reverts_batch_id")
        if rbid:
            rop_ids = record.get("reverts_op_ids")
            if rop_ids:
                if rbid not in per_op_reverted:
                    per_op_reverted[rbid] = set()
                per_op_reverted[rbid].update(rop_ids)
            else:
                fully_reverted_ids.add(rbid)

    batches = []
    op_counts: Counter = Counter()
    fix_kind_counts: Counter = Counter()
    chapters_edited: set[int] = set()
    total_batches = 0

    for record in all_records:
        if record.get("reverts_batch_id"):
            continue
        batch_id = record.get("batch_id")
        if batch_id in fully_reverted_ids:
            continue

        ops = record.get("operations", [])
        reverted_ops_for_batch = per_op_reverted.get(batch_id, set())
        if reverted_ops_for_batch:
            ops = [op for op in ops if op.get("op_id") not in reverted_ops_for_batch]
        if not ops and reverted_ops_for_batch:
            continue

        batch = {
            "batch_id": batch_id,
            "batch_type": record.get("batch_type"),
            "saved_at_utc": record.get("saved_at_utc"),
            "chapter": record.get("chapter"),
            "chapters": record.get("chapters"),
            "save_mode": record.get("save_mode"),
            "is_revert": False,
            "validation_summary_before": record.get("validation_summary_before"),
            "validation_summary_after": record.get("validation_summary_after"),
            "operations": ops,
        }
        if reverted_ops_for_batch:
            batch["reverted_op_ids"] = list(reverted_ops_for_batch)
        batches.append(batch)

        if ops:
            total_batches += 1
            ch = record.get("chapter")
            if ch is not None:
                chapters_edited.add(ch)
            for mch in record.get("chapters") or []:
                chapters_edited.add(mch)
            for op in ops:
                op_counts[op.get("op_type", "unknown")] += 1
                fix_kind_counts[op.get("fix_kind", "unknown")] += 1

    total_operations = sum(op_counts.values())
    summary = {
        "total_operations": total_operations,
        "total_batches": total_batches,
        "chapters_edited": len(chapters_edited),
        "op_counts": dict(op_counts),
        "fix_kind_counts": dict(fix_kind_counts),
    } if total_operations > 0 else None

    return jsonify({"batches": batches, "summary": summary})
