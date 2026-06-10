"""Per-reciter ``edit_history.jsonl`` v2 schema.

Per-batch ledger for in-app History panel browsing. v2 changes from v1:
- adds ``actor: {hf_user_id, login_at_time, role}``
- drops the file-hash chain (``file_hash_after``)
- drops the genesis record

The parser tolerates both schemas: ``parse_edit_history_line`` silently
ignores legacy ``file_hash_after`` / genesis fields so mixed v1/v2 files
read without a migration script.

Extras handling (Migration #5 single-source-of-truth):
- ``extra="forbid"`` + ``strip_and_warn`` pre-validator.
- Known-legacy keys (v0 + v1 record shapes) → INFO + strip.
- Unknown keys → WARNING + strip (surfaces writer/schema drift).

Spec: docs/planning/inspector-deploy/v2/inspector-deployment-plan.md §7 +
inspector-data-storage.md §8.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .._extras import strip_and_warn
from ..config.audit import Actor

# Legacy op-level fields we've seen on real prod buckets (audit survey,
# May 2026). Stripped on read with an INFO log; writers must never emit.
_OP_DEAD_FIELDS: set[str] = {
    # Migration #5 — per-op timestamps explicitly banned
    "applied_at_utc",
    "ready_at_utc",
    "started_at_utc",
    # v1 pipeline shape (replaced by op_type + targets_before/after)
    "affected_chapters",
    "command",
    "merge_direction",
    "op_context_category",
    "patch",
    "snapshots",
    "targetSegmentIndex",
    # v0 user-edit op aliases (replaced by kind/op_type)
    "type",
    "value",
    "field",
    "op",
}

# Legacy batch-level fields. The v1 genesis shape used a different vocab
# (``record_type=genesis`` + ``audio_source`` + ``extraction_params``);
# v0 used ``save_mode`` + ``chapter`` per-save. Both are stripped on read.
_BATCH_DEAD_FIELDS: set[str] = {
    "audio_source",
    "record_type",
    "created_at_utc",
    "extraction_params",
    "file_hash_after",
    "reciter",
    # short-lived FE-only metadata that leaked into save payloads
    "batch_pill",
    "batch_title",
    "child_edits",
    "parent_label",
    # v0 save_mode (replaced by batch_type)
    "save_mode",
}


class EditOperation(BaseModel):
    """One operation in a batch. Shape is intentionally permissive — the
    save flow owns the operation vocabulary (trim, split, merge, delete,
    etc.) and stores per-op payloads keyed by ``kind`` (user-driven) or
    ``op_type`` (pipeline-driven, written by ``.local/extraction/segments/
    post_passes.py``).

    Migration #5: pipeline ops carry ``op_type`` + ``fix_kind`` (no
    ``kind`` — that's a user-edit-only field set by the FE command store).
    ``kind`` is therefore optional. At least one of ``kind`` /
    ``op_type`` must be present for the op to be meaningful.

    ``targets_before`` / ``targets_after`` carry seg snapshots — list of
    dicts, not validated against ``DetailedSegment`` because snapshots
    intentionally carry extra fields (``chapter``, ``audio_url``,
    ``index_at_save``) that don't live on persisted segs.
    """

    model_config = ConfigDict(extra="forbid")

    op_id: str = Field(..., min_length=1)
    kind: str | None = None  # user-driven; absent for pipeline ops
    op_type: str | None = None  # pipeline-driven; absent for user ops

    # Migration #5 live fields, declared here instead of absorbed via extras.
    fix_kind: str | None = None  # only set by pipeline auto-fix ops
    targets_before: list[dict[str, Any]] = Field(default_factory=list)
    targets_after: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _surface_extras(cls, data: Any) -> Any:
        return strip_and_warn(
            data,
            declared=set(cls.model_fields),
            dead=_OP_DEAD_FIELDS,
            model_name="EditOperation",
        )


class EditHistoryBatch(BaseModel):
    """One JSONL line in ``edit_history.jsonl`` — a batch of operations.

    Migration #5 reality-check: both writers (Inspector save +
    ``.local/extraction/segments/post_passes.py``) stamp the timestamp as
    ``saved_at_utc`` (string). The legacy ``ts`` field has been retired
    from the schema; ``saved_at_utc`` is the canonical declared field.

    ``chapter`` (single) is written by Inspector save (one batch per
    chapter save). ``chapters`` (list) is written by the pipeline strip-
    specials post-pass (one batch can span multiple chapters when audio
    contains Basmala/Isti'adha at chapter starts). Exactly one of the
    two is present; both are tolerated for forward-compat.

    ``schema_version`` defaults to ``1`` matching the literal both writers
    emit; readers can bump to ``2`` later in a separate migration once
    both writers are updated together.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    batch_id: str = Field(..., min_length=1)
    saved_at_utc: str | None = None  # ISO-8601 UTC; canonical Migration #5
    actor: Actor | None = None
    operations: list[EditOperation] = Field(default_factory=list)

    # Per-batch chapter scope. Exactly one of these is set by a writer:
    #   - Inspector save → ``chapter`` (single, per-chapter save)
    #   - Pipeline strip-specials → ``chapters`` (list, multi-chapter run)
    chapter: int | None = None
    chapters: list[int] = Field(default_factory=list)

    # Pipeline-stamped: ``strip_specials`` / ``waqf_sakt`` etc.; user-edit
    # batches leave this None.
    batch_type: str | None = None

    # Optional cross-batch fields used by undo / revert filtering.
    reverts_batch_id: str | None = None
    reverts_op_ids: list[str] = Field(default_factory=list)

    # Inspector save legacy: pre-#5 batches embedded a snapshot of the
    # validation summary before/after the save. Migration #5 stopped
    # emitting these (the FE recomputes from live segs). Kept optional
    # so on-disk legacy batches parse.
    validation_summary_before: dict[str, Any] = Field(default_factory=dict)
    validation_summary_after: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _surface_extras(cls, data: Any) -> Any:
        return strip_and_warn(
            data,
            declared=set(cls.model_fields),
            dead=_BATCH_DEAD_FIELDS,
            model_name="EditHistoryBatch",
        )


def parse_edit_history_line(raw: str | bytes) -> EditHistoryBatch | None:
    """Parse one ``edit_history.jsonl`` line, tolerating v1 + v2 records.

    Returns ``None`` for legacy v1 genesis records (which carry neither
    a ``batch_id`` nor any user-visible operations). The detector matches
    both the v0 (``type=="genesis"``) and v1 (``record_type=="genesis"``)
    sentinels, plus the structural ``"batch_id" not in obj`` fallback for
    pre-batch_id record formats.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    text = raw.strip()
    if not text:
        return None
    obj = json.loads(text)

    if obj.get("type") == "genesis" or obj.get("record_type") == "genesis" or "batch_id" not in obj:
        return None

    return EditHistoryBatch.model_validate(obj)
