"""Save flow: atomic write, backup, history, rebuild_segments_json.

No Flask imports -- all functions accept parameters and return plain dicts.
"""

import json
from collections import defaultdict
from datetime import datetime, timezone

from adapters.save_payload import build_seg_lookups as _adapter_build_seg_lookups
from adapters.save_payload import make_seg as _adapter_make_seg
from adapters.segments_json import rebuild as _adapter_rebuild_segments
from config import RECITATION_SEGMENTS_PATH
from constants import HISTORY_SCHEMA_VERSION
from domain.command import validate_patch_dict
from services import cache
from services.data_loader import get_word_counts, load_detailed
from services.validation import chapter_validation_counts
from services.validation.registry import (
    apply_auto_suppress,
    filter_persistent_ignores,
)
from services.validation.snapshot_classifier import classify_snapshot
from utils.io import atomic_json_write, backup_file, file_sha256
from utils.references import chapter_from_ref, normalize_ref
from utils.uuid7 import uuid7


# Allowed ``command.type`` values.  Both wire-canonical (snake_case
# ``edit_reference`` / ``ignore_issue`` / ``auto_fix_missing_word``) and
# reducer-canonical (camelCase ``editReference`` / ``ignoreIssue`` /
# ``autoFixMissingWord``) shapes are accepted; the dispatchers and history
# round-trips emit the camelCase form, while round-trip and CLI fixtures use
# the snake_case form.
_ALLOWED_COMMAND_TYPES: frozenset[str] = frozenset({
    "trim",
    "split",
    "merge",
    "delete",
    "edit_reference",
    "editReference",
    "ignore_issue",
    "ignoreIssue",
    "auto_fix_missing_word",
    "autoFixMissingWord",
    # ``confirm_reference`` is a reducer-edge variant of editReference recorded
    # on ``op_type`` only; the ``command.type`` itself remains ``editReference``.
})


def _validate_command_envelopes(operations: list) -> str | None:
    """Return an error message if any op carries a malformed ``command`` envelope, else None.

    Each operation must carry a ``command`` object whose ``type`` is a known
    string and matches the enclosing ``op.type``.  Ops without a ``type`` (the
    pre-Phase-3 round-trip shape used by patch-only saves) are skipped to
    preserve MUST-1 (additive only).
    """
    for op in operations or []:
        if not isinstance(op, dict):
            continue
        op_type = op.get("type")
        if op_type is None:
            # Patch-style op without a discriminator; nothing to validate.
            continue
        cmd = op.get("command")
        if cmd is None:
            return "operation missing required `command` envelope"
        if not isinstance(cmd, dict):
            return "operation `command` must be a JSON object"
        cmd_type = cmd.get("type")
        if not isinstance(cmd_type, str):
            return "operation `command.type` must be a string"
        if cmd_type not in _ALLOWED_COMMAND_TYPES:
            return f"unknown command.type: {cmd_type!r}"
        if cmd_type != op_type:
            return (
                f"command.type {cmd_type!r} does not match op.type {op_type!r}"
            )
    return None


def _uids_with_explicit_ignored_categories(updates: dict) -> set[str]:
    """Return the set of segment_uids whose payload explicitly carries
    ``ignored_categories`` (including ``[]``).

    Used by ``_apply_registry_auto_suppress`` to honour MUST-7: when the
    payload sets the field explicitly we never override it from the registry.
    """
    out: set[str] = set()
    for s in (updates.get("segments") or []):
        if not isinstance(s, dict):
            continue
        if "ignored_categories" not in s:
            continue
        uid = s.get("segment_uid") or ""
        if uid:
            out.add(uid)
    return out


def _apply_registry_auto_suppress(
    matching: list[dict],
    operations: list,
    explicit_ic_uids: set[str],
) -> None:
    """Defensively write ``ignored_categories`` driven by the registry.

    For each operation that carries ``command.sourceCategory`` (or the
    wire-level ``op_context_category``) and targets a per-segment auto-suppress
    category, find the affected segment by ``command.segmentUid`` and append
    the category to its ``ignored_categories`` -- but only when the original
    payload omitted the field for that segment.  When the payload explicitly
    sent ``ignored_categories: []`` we leave it alone (MUST-7).

    The frontend reducer already runs this same registry gate; this backend
    pass is the defensive write for clients that bypass the reducer.
    """
    by_uid: dict[str, dict] = {}
    for entry in matching:
        for seg in entry.get("segments", []):
            uid = seg.get("segment_uid") or ""
            if uid:
                by_uid[uid] = seg

    for op in operations or []:
        if not isinstance(op, dict):
            continue
        cmd = op.get("command")
        if not isinstance(cmd, dict):
            continue
        category = cmd.get("sourceCategory") or op.get("op_context_category")
        if not isinstance(category, str) or not category:
            continue
        uid = cmd.get("segmentUid") or ""
        if not uid or uid in explicit_ic_uids:
            continue
        seg = by_uid.get(uid)
        if seg is None:
            continue
        apply_auto_suppress(seg, category, "card")
        # Re-filter so non-persistent categories (e.g. ``failed``) don't bleed
        # through to disk -- ``apply_auto_suppress`` only checks ``auto_suppress``,
        # but persistence is a separate gate.
        ic = filter_persistent_ignores(seg.get("ignored_categories") or [])
        if ic:
            seg["ignored_categories"] = ic
        else:
            seg.pop("ignored_categories", None)


def _validate_op_patches(operations: list) -> str | None:
    """Return an error message if any op has a malformed ``patch`` field, else None."""
    for op in operations or []:
        if not isinstance(op, dict):
            continue
        patch = op.get("patch")
        if patch is None:
            continue
        err = validate_patch_dict(patch)
        if err:
            return err
    return None


def _ensure_patch_on_ops(operations: list) -> list:
    """Return a copy of *operations* with a ``patch`` field on every op.

    Ops that already carry a ``patch`` are left unchanged.  Ops without one
    receive a minimal empty-patch envelope so the history record always has
    the field (forward-only: new records carry it; inverse-patch path in
    ``services/undo.py`` detects presence via ``"patch" in op``).

    # Forward-only: ops carrying a real patch from applyCommand round-trip
    # correctly through apply_inverse_patch. Ops missing a patch get an empty
    # envelope so undo detection (`if "patch" in op`) routes uniformly. Clients
    # that bypass applyCommand and don't send a patch will see no-op undo;
    # all production save flows must originate from applyCommand to preserve
    # undo correctness.
    """
    out: list = []
    for op in operations or []:
        if not isinstance(op, dict):
            out.append(op)
            continue
        if "patch" not in op:
            new_op = dict(op)
            new_op["patch"] = {
                "before": [],
                "after": [],
                "removedIds": [],
                "insertedIds": [],
                "affectedChapterIds": [],
            }
            out.append(new_op)
        else:
            out.append(op)
    return out


def _attach_classified_issues(operations: list) -> list:
    """Return a deep-enough copy of ``operations`` with ``classified_issues``
    populated on every snapshot.

    Handles both snapshot shapes the frontend can send:
    - ``op["targets_before"] = [snap, ...]`` and ``op["targets_after"]`` —
      arrays of snapshot dicts (live ops produced by ``snapshotSeg``).
    - ``op["snapshots"] = {"before": snap, "after": snap}`` — singular form
      used by some payload variants (and by the Phase-2 history test).

    Each snapshot dict gains a ``classified_issues: list[str]`` field
    derived by routing through the unified snapshot classifier. Non-dict
    snapshots are left untouched.
    """
    out: list = []
    for op in operations or []:
        if not isinstance(op, dict):
            out.append(op)
            continue
        new_op = dict(op)

        for key in ("targets_before", "targets_after"):
            arr = new_op.get(key)
            if not isinstance(arr, list):
                continue
            new_arr: list = []
            for snap in arr:
                if isinstance(snap, dict):
                    enriched = dict(snap)
                    enriched["classified_issues"] = classify_snapshot(enriched)
                    new_arr.append(enriched)
                else:
                    new_arr.append(snap)
            new_op[key] = new_arr

        snapshots = new_op.get("snapshots")
        if isinstance(snapshots, dict):
            new_snapshots = dict(snapshots)
            for which in ("before", "after"):
                snap = new_snapshots.get(which)
                if isinstance(snap, dict):
                    enriched = dict(snap)
                    enriched["classified_issues"] = classify_snapshot(enriched)
                    new_snapshots[which] = enriched
            new_op["snapshots"] = new_snapshots

        out.append(new_op)
    return out


def persist_detailed(reciter: str, meta: dict, entries: list[dict]) -> str:
    """Write detailed.json atomically, rebuild segments.json, return file hash.

    Shared helper consumed by both undo.py and (internally) save_seg_data.
    Does NOT append history — callers are responsible for that.
    """
    detailed_path = RECITATION_SEGMENTS_PATH / reciter / "detailed.json"
    segments_path = RECITATION_SEGMENTS_PATH / reciter / "segments.json"
    backup_file(detailed_path)
    backup_file(segments_path)
    atomic_json_write(detailed_path, {"_meta": meta, "entries": entries})
    file_hash = file_sha256(detailed_path)
    rebuild_segments_json(reciter, entries)
    return file_hash


def normalize_ref_with_wc(ref: str) -> str:
    """Normalize a short ref to canonical form (passes cached word counts)."""
    return normalize_ref(ref, get_word_counts())


def rebuild_segments_json(reciter: str, entries: list[dict]) -> None:
    """Regenerate segments.json from detailed entries (verse-aggregated format).

    Thin wrapper over ``adapters.segments_json.rebuild`` — preserves the
    ``(reciter, entries)`` calling convention used internally and by
    ``services.undo``.  The adapter accepts a ``Path`` so the reciter→path
    resolution lives here at the route boundary.
    """
    reciter_dir = RECITATION_SEGMENTS_PATH / reciter
    _adapter_rebuild_segments(reciter_dir, entries)


# ---------------------------------------------------------------------------
# save_seg_data — phase helpers
# Each helper owns one sequential phase of the orchestrator below.
# `_make_seg` is promoted to module-level with explicit lookup params.
# ---------------------------------------------------------------------------


def _build_seg_lookups(matching: list[dict]) -> tuple[dict, dict]:
    """Build ``(by_time, by_uid)`` lookups of existing segments for field preservation.

    Thin wrapper over ``adapters.save_payload.build_seg_lookups`` — kept under
    the ``_build_seg_lookups`` name because internal helpers reference it and
    pytest patches it in some cases.
    """
    return _adapter_build_seg_lookups(matching)


def _make_seg(
    s: dict,
    existing_by_time: dict,
    existing_by_uid: dict,
    word_counts: dict | None = None,
) -> dict:
    """Build a canonical segment dict, preserving fields from an existing match if any.

    Delegates to ``adapters.save_payload.make_seg``.  ``word_counts`` is
    resolved lazily via ``get_word_counts()`` when the caller does not supply
    one — preserving the historical behaviour where each call site relied on
    the ``services.cache``-backed lazy load.  Hot loops that build a single
    save batch should resolve once and pass the resolved dict explicitly.
    """
    if word_counts is None:
        word_counts = get_word_counts()
    return _adapter_make_seg(s, existing_by_time, existing_by_uid, word_counts)


def _apply_full_replace(matching: list[dict], updates: dict,
                       existing_by_time: dict, existing_by_uid: dict):
    """Mutate ``matching`` in place for a full_replace save.

    Returns ``None`` on success or an ``(error_dict, http_status)`` tuple on
    input validation failure (propagated by the caller as the route response).
    """
    word_counts = get_word_counts()
    if len(matching) == 1:
        matching[0]["segments"] = [
            _make_seg(s, existing_by_time, existing_by_uid, word_counts)
            for s in updates["segments"]
        ]
        return None

    entry_by_audio: dict[str, list[dict]] = defaultdict(list)
    for e in matching:
        audio = e.get("audio", "")
        if audio:
            entry_by_audio[audio].append(e)
        e["segments"] = []

    for s in updates["segments"]:
        seg_audio = s.get("audio_url", "")
        if not seg_audio:
            return {"error": (
                "Rejected structural save for by_ayah: segment payload is "
                "missing audio_url. Reload Inspector and try again."
            )}, 400

        candidates = entry_by_audio.get(seg_audio, [])
        if len(candidates) != 1:
            if len(candidates) == 0:
                return {"error": (
                    "Rejected structural save for by_ayah: segment audio_url "
                    "does not belong to this chapter."
                )}, 400
            return {"error": (
                "Rejected structural save for by_ayah: ambiguous audio_url "
                "matched multiple chapter entries."
            )}, 400

        candidates[0]["segments"].append(
            _make_seg(s, existing_by_time, existing_by_uid, word_counts)
        )
    return None


def _apply_patch(matching: list[dict], updates: dict) -> None:
    """Mutate ``matching`` in place for a patch save (field-level updates by index)."""
    flat_segments = []
    for e in matching:
        for seg in e.get("segments", []):
            flat_segments.append(seg)

    for upd in updates["segments"]:
        idx = upd.get("index")
        if idx is not None and 0 <= idx < len(flat_segments):
            flat_segments[idx]["matched_ref"] = normalize_ref_with_wc(upd.get("matched_ref", ""))
            flat_segments[idx]["matched_text"] = upd.get("matched_text", "")
            if "confidence" in upd:
                flat_segments[idx]["confidence"] = upd["confidence"]
            if "ignored_categories" in upd:
                ic = filter_persistent_ignores(upd.get("ignored_categories") or [])
                if ic:
                    flat_segments[idx]["ignored_categories"] = ic
                else:
                    flat_segments[idx].pop("ignored_categories", None)
                    flat_segments[idx].pop("ignored", None)


def _persist_and_record(reciter: str, chapter: int, entries: list[dict], meta: dict,
                        val_before: dict, updates: dict) -> dict:
    """Persist mutated entries to disk, append edit_history, invalidate caches."""
    # Validate patch envelopes before writing anything.
    raw_ops = updates.get("operations", [])
    patch_err = _validate_op_patches(raw_ops)
    if patch_err:
        return {"error": patch_err}, 400

    # Backup, write detailed.json atomically, rebuild segments.json
    file_hash = persist_detailed(reciter, meta, entries)

    # Snapshot validation counts after mutation and write batch record.
    # Each operation's snapshots gain a ``classified_issues`` field so the
    # frontend history-delta path reads it directly off the saved record
    # instead of running a second classifier pass on snapshot dicts.
    # Ops also receive a ``patch`` envelope when absent.
    val_after = chapter_validation_counts(entries, chapter, meta)
    operations = _attach_classified_issues(_ensure_patch_on_ops(raw_ops))
    batch = {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "batch_id": uuid7(),
        "reciter": reciter,
        "chapter": chapter,
        "saved_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "save_mode": "full_replace" if updates.get("full_replace") else "patch",
        "file_hash_after": file_hash,
        "validation_summary_before": val_before,
        "validation_summary_after": val_after,
        "operations": operations,
    }
    history_path = RECITATION_SEGMENTS_PATH / reciter / "edit_history.jsonl"
    backup_file(history_path)
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(batch, ensure_ascii=False) + "\n")

    # Invalidate cache
    cache.invalidate_seg_caches(reciter)

    return {"ok": True}


def save_seg_data(reciter: str, chapter: int, updates: dict) -> dict:
    """Save edited segments.  Returns ``{"ok": True}`` or ``{"error": ...}``
    with an HTTP status code as a second element in a tuple.
    """
    # Validate command envelopes on every op before any work is done.  Each
    # op declaring a discriminated ``type`` must carry a matching ``command``
    # object whose ``type`` is in the allowed set.  Rejection is additive
    # (MUST-1): historical patch-style ops without a ``type`` discriminator
    # pass through untouched.
    cmd_err = _validate_command_envelopes(updates.get("operations") or [])
    if cmd_err:
        return {"error": cmd_err}, 400

    entries = load_detailed(reciter)
    if not entries:
        return {"error": "Reciter not found"}, 404

    matching = [e for e in entries if chapter_from_ref(e["ref"]) == chapter]
    if not matching:
        return {"error": "Chapter not found"}, 404

    # Build lookups of existing segments by time and by uid for field preservation
    existing_by_time, existing_by_uid = _build_seg_lookups(matching)

    # Snapshot validation counts before mutation
    meta = cache.get_seg_meta(reciter)
    val_before = chapter_validation_counts(entries, chapter, meta)

    if updates.get("full_replace"):
        err = _apply_full_replace(matching, updates, existing_by_time, existing_by_uid)
        if err is not None:
            return err
    else:
        _apply_patch(matching, updates)

    # Defensive registry-driven auto-suppress write.  Honours MUST-7: when
    # the payload explicitly carries ``ignored_categories`` for a segment
    # (including ``[]``), we never override it from the registry.
    explicit_ic_uids = _uids_with_explicit_ignored_categories(updates)
    _apply_registry_auto_suppress(
        matching, updates.get("operations") or [], explicit_ic_uids,
    )

    return _persist_and_record(reciter, chapter, entries, meta, val_before, updates)
