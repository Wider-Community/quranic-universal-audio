"""Undo operations: batch reversal, snapshot verification, segment restoration.

No Flask imports -- all functions accept parameters and return plain dicts.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from config import RECITATION_SEGMENTS_PATH
from constants import HISTORY_SCHEMA_VERSION, VALIDATION_CATEGORIES
from services import cache
from services.data_loader import load_detailed
from services.save import persist_detailed
from services.validation import chapter_validation_counts
from services.history_query import parse_history_file
from utils.references import chapter_from_ref
from utils.uuid7 import uuid7


def find_segment_by_uid(entries: list[dict], uid: str, chapter_set: set[int]):
    """Find a segment by segment_uid within entries matching *chapter_set*.

    Returns ``(entry, seg_index, segment)`` or ``None``.
    """
    for entry in entries:
        ch = chapter_from_ref(entry["ref"])
        if ch not in chapter_set:
            continue
        for i, seg in enumerate(entry.get("segments", [])):
            if seg.get("segment_uid") == uid:
                return (entry, i, seg)
    return None


def find_entry_for_insert(entries: list[dict], snap: dict, chapter_set: set[int]):
    """Find the correct entry to insert a restored segment into.

    For by_surah: single entry per chapter.
    For by_ayah: match by audio_url from the snapshot.
    """
    audio_url = snap.get("audio_url", "")
    for entry in entries:
        ch = chapter_from_ref(entry["ref"])
        if ch not in chapter_set:
            continue
        if audio_url and entry.get("audio", "") == audio_url:
            return entry
        if not audio_url:
            return entry
    for entry in entries:
        ch = chapter_from_ref(entry["ref"])
        if ch in chapter_set:
            return entry
    return None


def snap_to_segment(snap: dict) -> dict:
    """Convert a snapshot to a segment dict for insertion."""
    seg = {
        "segment_uid": snap.get("segment_uid", uuid7()),
        "time_start": snap["time_start"],
        "time_end": snap["time_end"],
        "matched_ref": snap.get("matched_ref", ""),
        "matched_text": snap.get("matched_text", ""),
        "confidence": snap.get("confidence", 0),
    }
    if snap.get("has_repeated_words"):
        seg["has_repeated_words"] = True
    if snap.get("wrap_word_ranges"):
        seg["wrap_word_ranges"] = snap["wrap_word_ranges"]
    if snap.get("phonemes_asr"):
        seg["phonemes_asr"] = snap["phonemes_asr"]
    if snap.get("ignored_categories"):
        seg["ignored_categories"] = list(snap["ignored_categories"])
    return seg


def _restore_ignored_categories(seg: dict, snap: dict) -> None:
    """Restore per-category ignore markers from a snapshot."""
    if snap.get("ignored_categories"):
        seg["ignored_categories"] = list(snap["ignored_categories"])
    else:
        seg.pop("ignored_categories", None)
        seg.pop("ignored", None)


def verify_segment_matches_snapshot(seg: dict, snap: dict) -> str | None:
    """Check if a current segment matches its expected snapshot state.

    Returns an error message if there's a conflict, ``None`` if OK.
    """
    uid = snap.get("segment_uid", "")
    if seg.get("time_start") != snap.get("time_start") or seg.get("time_end") != snap.get("time_end"):
        return (
            f"Segment {uid} times changed since this save "
            f"(expected {snap.get('time_start')}-{snap.get('time_end')}, "
            f"found {seg.get('time_start')}-{seg.get('time_end')})"
        )
    if seg.get("matched_ref", "") != snap.get("matched_ref", ""):
        return f"Segment {uid} reference changed since this save"
    return None


# ---------------------------------------------------------------------------
# Shared find + verify helper
# ---------------------------------------------------------------------------

def _find_and_verify(entries: list[dict], snap_after: dict,
                     chapter_set: set[int]) -> tuple[dict, int, dict]:
    """Look up a segment by UID and verify it matches *snap_after*.

    Returns ``(entry, index, seg)`` or raises ``ValueError`` on conflict.
    """
    uid = snap_after.get("segment_uid", "")
    found = find_segment_by_uid(entries, uid, chapter_set)
    if not found:
        raise ValueError(f"Segment {uid} not found — it may have been deleted by a later edit")
    entry, idx, seg = found
    conflict = verify_segment_matches_snapshot(seg, snap_after)
    if conflict:
        raise ValueError(conflict)
    return entry, idx, seg


# ---------------------------------------------------------------------------
# Per-op-type branch helpers
# ---------------------------------------------------------------------------

def _reverse_trim(entries: list[dict], op: dict, chapter_set: set[int]) -> None:
    """Reverse a trim_segment or auto_fix_missing_word operation."""
    before = op.get("targets_before", [])
    after = op.get("targets_after", [])
    if not after or not before:
        return
    entry, idx, seg = _find_and_verify(entries, after[0], chapter_set)
    snap_before = before[0]
    seg["time_start"] = snap_before["time_start"]
    seg["time_end"] = snap_before["time_end"]
    seg["matched_ref"] = snap_before.get("matched_ref", "")
    seg["matched_text"] = snap_before.get("matched_text", "")
    seg["confidence"] = snap_before.get("confidence", 0)
    _restore_ignored_categories(seg, snap_before)
    entry["segments"].sort(key=lambda s: s["time_start"])


def _reverse_split(entries: list[dict], op: dict, chapter_set: set[int]) -> None:
    """Reverse a split_segment operation."""
    before = op.get("targets_before", [])
    after = op.get("targets_after", [])
    if len(after) < 2 or not before:
        return
    found_list = []
    for snap_after in after:
        uid = snap_after.get("segment_uid", "")
        found = find_segment_by_uid(entries, uid, chapter_set)
        if not found:
            raise ValueError(f"Segment {uid} not found — it may have been modified by a later edit")
        conflict = verify_segment_matches_snapshot(found[2], snap_after)
        if conflict:
            raise ValueError(conflict)
        found_list.append(found)
    entry = found_list[0][0]
    indices = sorted([f[1] for f in found_list], reverse=True)
    for idx in indices:
        entry["segments"].pop(idx)
    restored = snap_to_segment(before[0])
    entry["segments"].append(restored)
    entry["segments"].sort(key=lambda s: s["time_start"])


def _reverse_merge(entries: list[dict], op: dict, chapter_set: set[int]) -> None:
    """Reverse a merge_segments or waqf_sakt operation."""
    before = op.get("targets_before", [])
    after = op.get("targets_after", [])
    if not after or not before:
        return
    entry, idx, _ = _find_and_verify(entries, after[0], chapter_set)
    entry["segments"].pop(idx)
    for snap_before in before:
        restored = snap_to_segment(snap_before)
        entry["segments"].append(restored)
    entry["segments"].sort(key=lambda s: s["time_start"])


def _reverse_delete(entries: list[dict], op: dict, chapter_set: set[int]) -> None:
    """Reverse a delete_segment operation."""
    before = op.get("targets_before", [])
    if not before:
        return
    snap_before = before[0]
    entry = find_entry_for_insert(entries, snap_before, chapter_set)
    if not entry:
        raise ValueError("Could not find entry to restore deleted segment into")
    restored = snap_to_segment(snap_before)
    entry["segments"].append(restored)
    entry["segments"].sort(key=lambda s: s["time_start"])


def _reverse_ref_edit(entries: list[dict], op: dict, chapter_set: set[int]) -> None:
    """Reverse an edit_reference, confirm_reference, or remove_sadaqa operation."""
    before = op.get("targets_before", [])
    after = op.get("targets_after", [])
    if not after or not before:
        return
    _, _, seg = _find_and_verify(entries, after[0], chapter_set)
    snap_before = before[0]
    seg["matched_ref"] = snap_before.get("matched_ref", "")
    seg["matched_text"] = snap_before.get("matched_text", "")
    seg["confidence"] = snap_before.get("confidence", 0)
    _restore_ignored_categories(seg, snap_before)


def _reverse_ignore(entries: list[dict], op: dict, chapter_set: set[int]) -> None:
    """Reverse an ignore_issue operation."""
    before = op.get("targets_before", [])
    after = op.get("targets_after", [])
    if not after or not before:
        return
    _, _, seg = _find_and_verify(entries, after[0], chapter_set)
    snap_before = before[0]
    seg["confidence"] = snap_before.get("confidence", 0)
    _restore_ignored_categories(seg, snap_before)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def apply_reverse_op(entries: list[dict], op: dict, chapter_set: set[int]) -> None:
    """Apply the reverse of a single operation.  Raises ``ValueError`` on conflict."""
    op_type = op.get("op_type", "")
    if op_type in ("trim_segment", "auto_fix_missing_word"):
        _reverse_trim(entries, op, chapter_set)
    elif op_type == "split_segment":
        _reverse_split(entries, op, chapter_set)
    elif op_type in ("merge_segments", "waqf_sakt"):
        _reverse_merge(entries, op, chapter_set)
    elif op_type == "delete_segment":
        _reverse_delete(entries, op, chapter_set)
    elif op_type in ("edit_reference", "confirm_reference", "remove_sadaqa"):
        _reverse_ref_edit(entries, op, chapter_set)
    elif op_type == "ignore_issue":
        _reverse_ignore(entries, op, chapter_set)


# ---------------------------------------------------------------------------
# Internal helpers (used by undo_batch / undo_ops)
# ---------------------------------------------------------------------------

def _get_affected_chapters(batch: dict) -> set[int]:
    """Extract all affected chapters from a batch record."""
    affected = set()
    ch = batch.get("chapter")
    if ch is not None:
        affected.add(ch)
    chs = batch.get("chapters")
    if chs:
        affected.update(chs)
    return affected


def _append_revert_record(history_path: Path, target_batch_id: str, reciter: str,
                          chapter, chapters, file_hash: str,
                          val_before: dict, val_after: dict,
                          reverts_op_ids: list[str] | None = None) -> None:
    """Append a revert record to edit_history.jsonl."""
    from utils.io import backup_file
    backup_file(history_path)
    revert = {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "batch_id": uuid7(),
        "reverts_batch_id": target_batch_id,
        "reciter": reciter,
        "chapter": chapter,
        "saved_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "file_hash_after": file_hash,
        "validation_summary_before": val_before,
        "validation_summary_after": val_after,
        "operations": [],
    }
    if reverts_op_ids:
        revert["reverts_op_ids"] = reverts_op_ids
    if chapters:
        revert["chapters"] = chapters
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(revert, ensure_ascii=False) + "\n")


def _merge_val_summaries(val_map: dict[int, dict]) -> dict:
    """Merge per-chapter validation summaries into one."""
    merged = {}
    for cat in VALIDATION_CATEGORIES:
        merged[cat] = sum(v.get(cat, 0) for v in val_map.values())
    return merged


# ---------------------------------------------------------------------------
# Public undo entry points
# ---------------------------------------------------------------------------

def undo_batch(reciter: str, target_batch_id: str) -> dict | tuple:
    """Undo a specific saved batch.  Returns result dict or (error_dict, status)."""
    history_path = RECITATION_SEGMENTS_PATH / reciter / "edit_history.jsonl"
    if not history_path.exists():
        return {"error": "No edit history found"}, 404

    all_records = parse_history_file(history_path)

    target_batch = None
    for rec in all_records:
        if rec.get("batch_id") == target_batch_id:
            target_batch = rec
            break
    if not target_batch:
        return {"error": "Batch not found"}, 404

    if target_batch.get("reverts_batch_id"):
        return {"error": "Cannot undo a revert record"}, 400

    already_reverted = {
        r.get("reverts_batch_id") for r in all_records
        if r.get("reverts_batch_id") and not r.get("reverts_op_ids")
    }
    if target_batch_id in already_reverted:
        return {"error": "This batch has already been undone"}, 400

    operations = target_batch.get("operations", [])
    if not operations:
        return {"error": "Batch has no operations to undo"}, 400

    # Skip ops already individually undone
    per_op_reverted = set()
    for r in all_records:
        if r.get("reverts_batch_id") == target_batch_id and r.get("reverts_op_ids"):
            per_op_reverted.update(r["reverts_op_ids"])
    if per_op_reverted:
        operations = [op for op in operations if op.get("op_id") not in per_op_reverted]
        if not operations:
            return {"error": "All operations in this batch have already been individually undone"}, 400

    entries = load_detailed(reciter)
    if not entries:
        return {"error": "Reciter data not found"}, 404

    meta = cache.get_seg_meta(reciter)
    affected_chapters = _get_affected_chapters(target_batch)

    val_before_all = {ch: chapter_validation_counts(entries, ch, meta) for ch in affected_chapters}

    try:
        for op in reversed(operations):
            apply_reverse_op(entries, op, affected_chapters)
    except ValueError as e:
        return {"error": str(e)}, 409

    file_hash = persist_detailed(reciter, meta, entries)

    val_after_all = {ch: chapter_validation_counts(entries, ch, meta) for ch in affected_chapters}
    val_before = _merge_val_summaries(val_before_all)
    val_after = _merge_val_summaries(val_after_all)

    _append_revert_record(
        history_path, target_batch_id, reciter,
        target_batch.get("chapter"), target_batch.get("chapters"),
        file_hash, val_before, val_after,
    )

    cache.invalidate_seg_caches(reciter)
    return {"ok": True, "operations_reversed": len(operations)}


def undo_ops(reciter: str, target_batch_id: str, requested_op_ids: set[str]) -> dict | tuple:
    """Undo specific operations within a saved batch.

    Returns result dict or ``(error_dict, status)``.
    """
    history_path = RECITATION_SEGMENTS_PATH / reciter / "edit_history.jsonl"
    if not history_path.exists():
        return {"error": "No edit history found"}, 404

    all_records = parse_history_file(history_path)

    target_batch = None
    for rec in all_records:
        if rec.get("batch_id") == target_batch_id:
            target_batch = rec
            break
    if not target_batch:
        return {"error": "Batch not found"}, 404

    if target_batch.get("reverts_batch_id"):
        return {"error": "Cannot undo operations in a revert record"}, 400

    fully_reverted = {
        r.get("reverts_batch_id") for r in all_records
        if r.get("reverts_batch_id") and not r.get("reverts_op_ids")
    }
    if target_batch_id in fully_reverted:
        return {"error": "This batch has already been fully undone"}, 400

    already_reverted_ops = set()
    for r in all_records:
        if r.get("reverts_batch_id") == target_batch_id and r.get("reverts_op_ids"):
            already_reverted_ops.update(r["reverts_op_ids"])

    already_undone = requested_op_ids & already_reverted_ops
    if already_undone:
        return {"error": f"Operation(s) already undone: {', '.join(already_undone)}"}, 400

    all_op_ids = {op.get("op_id") for op in target_batch.get("operations", [])}
    missing = requested_op_ids - all_op_ids
    if missing:
        return {"error": f"Operation(s) not found in batch: {', '.join(missing)}"}, 404

    ops_to_undo = [op for op in target_batch.get("operations", []) if op.get("op_id") in requested_op_ids]

    entries = load_detailed(reciter)
    if not entries:
        return {"error": "Reciter data not found"}, 404

    meta = cache.get_seg_meta(reciter)
    affected_chapters = _get_affected_chapters(target_batch)

    val_before_all = {ch: chapter_validation_counts(entries, ch, meta) for ch in affected_chapters}

    try:
        for op in reversed(ops_to_undo):
            apply_reverse_op(entries, op, affected_chapters)
    except ValueError as e:
        return {"error": str(e)}, 409

    file_hash = persist_detailed(reciter, meta, entries)

    val_after_all = {ch: chapter_validation_counts(entries, ch, meta) for ch in affected_chapters}
    val_before = _merge_val_summaries(val_before_all)
    val_after = _merge_val_summaries(val_after_all)

    _append_revert_record(
        history_path, target_batch_id, reciter,
        target_batch.get("chapter"), target_batch.get("chapters"),
        file_hash, val_before, val_after,
        reverts_op_ids=list(requested_op_ids),
    )

    cache.invalidate_seg_caches(reciter)
    return {"ok": True, "operations_reversed": len(ops_to_undo)}
