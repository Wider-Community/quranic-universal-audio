"""Per-reciter ``edit_history.jsonl`` v2 schema.

Per-batch ledger for in-app History panel browsing. v2 changes from v1:
- adds ``actor: {hf_user_id, login_at_time, role}``
- drops the file-hash chain (``file_hash_after``)
- drops the genesis record

The parser tolerates both schemas: ``parse_edit_history_line`` silently
ignores legacy ``file_hash_after`` / genesis fields so mixed v1/v2 files
read without a migration script.

Spec: docs/planning/inspector-deploy/v2/inspector-deployment-plan.md §7 +
inspector-data-storage.md §8.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .audit import Actor


class EditOperation(BaseModel):
    """One operation in a batch. Shape is intentionally permissive — the
    save flow owns the operation vocabulary (trim, split, merge, delete,
    etc.) and stores per-op payloads keyed by ``kind`` (user-driven) or
    ``op_type`` (pipeline-driven, written by ``.local/extraction/segments/
    post_passes.py``).

    Migration #5: pipeline ops carry ``op_type`` + ``fix_kind`` (no
    ``kind`` — that's a user-edit-only field set by the FE command store).
    ``kind`` is therefore optional. At least one of ``kind`` /
    ``op_type`` must be present for the op to be meaningful, but readers
    handle either via ``extra="allow"``.
    """

    model_config = ConfigDict(extra="allow")

    op_id: str = Field(..., min_length=1)
    kind: str | None = None  # user-driven; absent for pipeline ops
    op_type: str | None = None  # pipeline-driven; absent for user ops


class EditHistoryBatch(BaseModel):
    """One JSONL line in ``edit_history.jsonl`` — a batch of operations.

    Migration #5 reality-check: both writers (Inspector save +
    `.local/extraction/segments/post_passes.py`) stamp the timestamp as
    ``saved_at_utc`` (string), NOT ``ts`` (datetime). Both writers
    historically wrote ``schema_version: 1``, not ``2``. The schema is
    permissive on both axes so the actual on-disk shape parses without
    a schema bump:

    - ``ts`` is optional; ``saved_at_utc`` lands via ``extra="allow"``.
    - ``schema_version`` defaults to ``1`` matching the literal both
      writers emit; readers can bump to ``2`` later in a separate
      migration once both writers are updated together.
    - ``actor`` is optional — Inspector save writes it; the pipeline
      now also writes it (constant ``{"hf_user_id": "pipeline", ...}``)
      but legacy pre-#5 pipeline batches don't have it.
    """

    model_config = ConfigDict(extra="allow")  # tolerate legacy fields on read

    schema_version: int = 1
    batch_id: str = Field(..., min_length=1)
    ts: datetime | None = None
    actor: Actor | None = None
    operations: list[EditOperation] = Field(default_factory=list)

    # Optional cross-batch fields used by undo / revert filtering.
    reverts_batch_id: str | None = None
    reverts_op_ids: list[str] = Field(default_factory=list)

    # Legacy pre-Migration #5 fields — both writers stopped emitting these
    # in Inspector save (commit b8aa414) and in extraction (Migration #5).
    # Kept as optional so on-disk legacy batches parse.
    validation_summary_before: dict[str, Any] = Field(default_factory=dict)
    validation_summary_after: dict[str, Any] = Field(default_factory=dict)


def parse_edit_history_line(raw: str | bytes) -> EditHistoryBatch | None:
    """Parse one ``edit_history.jsonl`` line, tolerating v1 + v2 records.

    Returns ``None`` for the legacy v1 genesis record (which has no
    ``batch_id`` / ``operations``) so callers can `filter()` it out
    without per-call special-casing.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    text = raw.strip()
    if not text:
        return None
    obj = json.loads(text)

    # v1 genesis record: ``{"type": "genesis", "file_hash_after": "...", ...}``
    if obj.get("type") == "genesis" or "batch_id" not in obj:
        return None

    # Drop v1 chain fields silently; pydantic ``extra='allow'`` lets us
    # keep unknown fields without erroring, but ``file_hash_after`` is
    # explicitly meaningless in v2 readers.
    obj.pop("file_hash_after", None)

    return EditHistoryBatch.model_validate(obj)
