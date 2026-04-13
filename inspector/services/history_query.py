"""Query helpers for Segments-tab edit-history endpoint.

No Flask imports -- functions accept parameters and return plain dicts/lists.
Extracted from ``routes/segments_validation.py`` in Wave 2b
(stage2-plan.md §4) as a pure behavior-preserving move. Undo logic for
reverse-applying history entries lives in ``services/undo.py``; this module
is read-only.
"""

import json
from collections import Counter

from config import RECITATION_SEGMENTS_PATH


def load_edit_history(reciter: str) -> dict:
    """Return ``{batches, summary}`` for a reciter's edit_history.jsonl.

    Filters fully-reverted batches, strips per-op reverts, and aggregates
    summary statistics. Returns ``{"batches": [], "summary": None}`` when the
    reciter has no edit history file yet.
    """
    history_path = RECITATION_SEGMENTS_PATH / reciter / "edit_history.jsonl"
    if not history_path.exists():
        return {"batches": [], "summary": None}

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

    return {"batches": batches, "summary": summary}
