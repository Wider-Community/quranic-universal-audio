"""Save flow: write through storage backend, history append, rebuild segments.

No Flask imports -- all functions accept parameters and return plain dicts.

Writes go through ``services.data_dir`` which routes to ``BucketBackend`` or
``FilesystemBackend`` based on ``INSPECTOR_BACKEND``. Per-save
``huggingface_hub.upload_file()`` is wired into ``BucketBackend`` itself
(force_flush_on_write), so the save path doesn't need to think about
durability — it just calls the backend.

Phase 3 made ``@require_edit_lock`` (signed-in + claim + state checks) the
sole authoritative writer gate. The earlier ``INSPECTOR_LOCAL_WRITES`` env
guard is gone — both local and deployed modes route every mutation through
the same OAuth + claim check on the route layer.
"""

from collections import defaultdict
from datetime import datetime, timezone

from adapters.save_payload import build_seg_lookups as _adapter_build_seg_lookups
from adapters.save_payload import make_seg as _adapter_make_seg
from adapters.segments_json import build_segments_doc as _adapter_build_segments_doc
from constants import HISTORY_SCHEMA_VERSION
from domain.command import validate_patch_dict
from scripts.lib.schemas import Actor
from services.storage import cache, data_dir
from services.storage.data_loader import get_word_counts, load_detailed, load_probe_v2
from services.audio.peaks_history import append_peaks_records
from services.segments.qalqala import compute_qalqala_letter
from services.reference.quran_refs import dk_text_for_ref
from services.validation.registry import filter_persistent_ignores
from services.validation.snapshot_classifier import classify_snapshot
from utils.references import chapter_from_ref, normalize_ref
from utils.uuid7 import uuid7

# Categories that should not surface in the History panel's per-op
# "classified_issues" deltas. They exist in the validation accordion for
# review/awareness but represent display-only context, not gains/losses
# from an edit.
#   - ``basmala_amin`` flags verse-boundary basmala / amin conventions and
#     would otherwise show up as a noisy +/- pill on every boundary edit.
#   - ``muqattaat`` flags huruf-muqattaʼat verse openings — display-only.
HISTORY_NEUTRAL_CATEGORIES = frozenset({"basmala_amin", "muqattaat"})


def _history_visible_categories(categories: list[str]) -> list[str]:
    return [cat for cat in categories if cat not in HISTORY_NEUTRAL_CATEGORIES]


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


def _attach_classified_issues(operations: list,
                               probe_failed_uids: set | None = None) -> list:
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

    ``probe_failed_uids`` (when provided) lets the snapshot classifier
    surface the *Low Confidence v2* category — same uid set used for the
    live validation pass — so resolved/introduced v2 flags appear in the
    history-row delta with the same ``low conf`` pill as v1.
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
                    enriched["classified_issues"] = _history_visible_categories(
                        classify_snapshot(enriched, probe_failed_uids=probe_failed_uids)
                    )
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
                    enriched["classified_issues"] = _history_visible_categories(
                        classify_snapshot(enriched, probe_failed_uids=probe_failed_uids)
                    )
                    new_snapshots[which] = enriched
            new_op["snapshots"] = new_snapshots

        out.append(new_op)
    return out


def persist_detailed(reciter: str, meta: dict, entries: list[dict]) -> None:
    """Write detailed.json atomically; rebuild segments.json.

    Shared helper consumed by both undo.py and (internally) save_seg_data.
    Does NOT append history — callers are responsible for that.

    v2: writes go through ``data_dir`` (storage backend). No ``.bak`` files
    (audit log + edit_history.jsonl are the recovery surface). No file
    hash returned — the file-hash chain is removed in v2.
    """
    # Strip transient ``_resolved_by_edit`` (set, injected by validate route)
    # — concurrent validate may have left it on cached segs mid-flight.
    for entry in entries:
        for seg in entry.get("segments", []):
            seg.pop("_resolved_by_edit", None)
    data_dir.write_detailed_doc(reciter, {"_meta": meta, "entries": entries})
    rebuild_segments_json(reciter, entries)


def normalize_ref_with_wc(ref: str) -> str:
    """Normalize a short ref to canonical form (passes cached word counts)."""
    return normalize_ref(ref, get_word_counts())


def rebuild_segments_json(reciter: str, entries: list[dict]) -> None:
    """Regenerate segments.json from detailed entries (verse-aggregated format).

    Reads the existing ``_meta`` block from the on-bucket ``segments.json``
    so the freshly-built doc preserves the meta block intact, then writes the
    rebuilt doc via the storage backend.
    """
    existing = data_dir.read_segments_doc(reciter)
    existing_meta = (existing or {}).get("_meta", {})
    seg_doc = _adapter_build_segments_doc(entries, existing_meta)
    data_dir.write_segments_doc(reciter, seg_doc)


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


def _stamp_persisted_classifier_fields(seg: dict, single_word_verses: set | None = None) -> None:
    """Set the per-seg fields the validate fast-path reads instead of recomputing.

    Called by every save path that mutates a segment dict; ensures
    ``qalqala_letter`` and ``is_boundary_adj`` stay in lockstep with
    ``matched_ref`` / ``matched_text`` after an edit.

    ``is_boundary_adj`` is computed structural-only here (``canonical=None``):
    the phonemic side of boundary_adj depends on ``phonemes_asr`` which is
    only set at extraction time and never touched by user edits, so stamping
    it without canonical is correct for save-time mutations. The backfill
    script DOES pass canonical so historical phonemic detections are captured.
    """
    from services.validation.classifier import compute_is_boundary_adj
    seg["qalqala_letter"] = compute_qalqala_letter(seg)

    if single_word_verses is None:
        wc = get_word_counts()
        single_word_verses = {k for k, v in wc.items() if v == 1}

    matched_ref = seg.get("matched_ref") or ""
    parts = matched_ref.split("-")
    if len(parts) == 2:
        sp = parts[0].split(":")
        ep = parts[1].split(":")
        if len(sp) == 3 and len(ep) == 3:
            try:
                surah = int(sp[0])
                s_ayah = int(sp[1])
                s_word = int(sp[2])
                e_word = int(ep[2])
                seg["is_boundary_adj"] = compute_is_boundary_adj(
                    seg, surah, s_ayah, s_word, e_word, single_word_verses, None,
                )
                return
            except ValueError:
                pass
    seg["is_boundary_adj"] = False


def _apply_full_replace(matching: list[dict], updates: dict,
                       existing_by_time: dict, existing_by_uid: dict):
    """Mutate ``matching`` in place for a full_replace save.

    Returns ``None`` on success or an ``(error_dict, http_status)`` tuple on
    input validation failure (propagated by the caller as the route response).
    """
    word_counts = get_word_counts()
    single_word_verses = {k for k, v in word_counts.items() if v == 1}
    if len(matching) == 1:
        new_segs = [
            _make_seg(s, existing_by_time, existing_by_uid, word_counts)
            for s in updates["segments"]
        ]
        for seg in new_segs:
            _stamp_persisted_classifier_fields(seg, single_word_verses)
        matching[0]["segments"] = new_segs
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

        new_seg = _make_seg(s, existing_by_time, existing_by_uid, word_counts)
        _stamp_persisted_classifier_fields(new_seg, single_word_verses)
        candidates[0]["segments"].append(new_seg)
    return None


def _apply_patch(matching: list[dict], updates: dict) -> None:
    """Mutate ``matching`` in place for a patch save (field-level updates by index)."""
    flat_segments = []
    for e in matching:
        for seg in e.get("segments", []):
            flat_segments.append(seg)

    word_counts = get_word_counts()
    single_word_verses = {k for k, v in word_counts.items() if v == 1}
    for upd in updates["segments"]:
        idx = upd.get("index")
        if idx is not None and 0 <= idx < len(flat_segments):
            ref = normalize_ref_with_wc(upd.get("matched_ref", ""))
            flat_segments[idx]["matched_ref"] = ref
            # FE no longer echoes matched_text; derive from dk_words so the
            # disk schema stays consistent with the new ref. Legacy clients
            # that still send a value override the derivation.
            flat_segments[idx]["matched_text"] = upd.get("matched_text") or dk_text_for_ref(ref)
            if "confidence" in upd:
                flat_segments[idx]["confidence"] = upd["confidence"]
            if "ignored_categories" in upd:
                ic = filter_persistent_ignores(upd.get("ignored_categories") or [])
                if ic:
                    flat_segments[idx]["ignored_categories"] = ic
                else:
                    flat_segments[idx].pop("ignored_categories", None)
                    flat_segments[idx].pop("ignored", None)
            # Re-stamp persisted classifier fields since matched_ref/text changed.
            _stamp_persisted_classifier_fields(flat_segments[idx], single_word_verses)


def _persist_and_record(reciter: str, chapter: int, entries: list[dict], meta: dict,
                        updates: dict, *, actor: Actor) -> dict:
    """Persist mutated entries to disk, append edit_history, invalidate caches."""
    # Validate patch envelopes before writing anything.
    raw_ops = updates.get("operations", [])
    patch_err = _validate_op_patches(raw_ops)
    if patch_err:
        return {"error": patch_err}, 400

    # Write detailed.json + rebuild segments.json via storage backend.
    persist_detailed(reciter, meta, entries)

    # Each operation's snapshots gain a ``classified_issues`` field so the
    # frontend history-delta path reads it directly off the saved record
    # instead of running a second classifier pass on snapshot dicts.
    # Ops also receive a ``patch`` envelope when absent.
    probe_failed_uids, _ = load_probe_v2(reciter)
    operations = _attach_classified_issues(
        _ensure_patch_on_ops(raw_ops), probe_failed_uids=probe_failed_uids,
    )
    # v2: no ``file_hash_after`` (chain removed in Phase 1). ``actor`` block
    # carries the per-edit attribution that replaces the v1 per-edit GitHub
    # commit Co-authored-by surface; surfaced in the History panel and feeds
    # the future contributor-recognition page.
    batch = {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "batch_id": uuid7(),
        "chapter": chapter,
        "saved_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "save_mode": "full_replace" if updates.get("full_replace") else "patch",
        "operations": operations,
        "actor": actor.model_dump(mode="json"),
    }
    data_dir.append_edit_history(reciter, batch)

    # Persist any op-level peaks the client gathered from its in-memory cache
    # so cross-session History viewing works without re-computing. Best-effort:
    # malformed entries are silently skipped (lazy compute-on-play fills gaps).
    op_peaks = updates.get("op_peaks")
    if isinstance(op_peaks, list) and op_peaks:
        append_peaks_records(reciter, op_peaks, batch_id=batch["batch_id"])

    # Invalidate cache
    cache.invalidate_seg_caches(reciter)

    return {"ok": True}


def save_seg_data(reciter: str, chapter: int, updates: dict, *, actor: Actor) -> dict:
    """Save edited segments.  Returns ``{"ok": True}`` or ``{"error": ...}``
    with an HTTP status code as a second element in a tuple.

    ``actor`` (kw-only) carries the per-edit attribution stamped on every
    new edit_history.jsonl batch. The route layer builds it from the
    authenticated user (see ``inspector/routes/segments_edit.py``).
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

    meta = cache.get_seg_meta(reciter)

    if updates.get("full_replace"):
        err = _apply_full_replace(matching, updates, existing_by_time, existing_by_uid)
        if err is not None:
            return err
    else:
        _apply_patch(matching, updates)

    # ``ignored_categories`` is mutated only when the payload explicitly
    # carries it (Ignore action, or explicit ``[]`` clear -- MUST-7).
    # Edits dispatched from validation accordion cards no longer write to
    # ``ignored_categories``: that contract is reserved for explicit Ignore.
    # Card dismissal for soft-rule categories is purely a frontend
    # session-state concern.
    return _persist_and_record(
        reciter, chapter, entries, meta, updates, actor=actor,
    )
