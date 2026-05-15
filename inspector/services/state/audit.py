"""Audit log service: per-month JSONL partitions on the bucket.

Append-only. Inspector backend is sole writer. State + catalog + access +
admin events all go through ``append()``. Direct upload per record (bypasses
the mount's 2-30 s flush window) — audit durability matters more than
latency for state-changing events.

Spec: docs/planning/inspector-deploy/v2/inspector-state-management.md §2.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from scripts.lib.schemas import Actor, AuditRecord

from services.storage import storage_paths
from services.storage.hf_bucket import get_backend

logger = logging.getLogger(__name__)

_append_lock = threading.Lock()


def append(
    event: str,
    *,
    actor: Actor,
    slug: str | None = None,
    from_state: str | None = None,
    to_state: str | None = None,
    payload: dict[str, Any] | None = None,
    request_id: str | None = None,
    reason: str | None = None,
    result: Literal["ok", "error"] = "ok",
    ts: datetime | None = None,
) -> AuditRecord:
    """Validate + persist one audit record. Returns the persisted record.

    Serialized by a module-level lock so per-partition appends never
    interleave across threads. Per-slug serialization happens upstream in
    ``services/state.transition()``; this lock is the partition-level
    backstop.
    """
    if ts is None:
        ts = datetime.now(timezone.utc)

    record = AuditRecord(
        ts=ts,
        event=event,
        slug=slug,
        from_state=from_state,
        to_state=to_state,
        actor=actor,
        payload=payload or {},
        request_id=request_id or _new_request_id(),
        reason=reason,
        result=result,
    )

    partition = storage_paths.audit_partition_path(ts)
    payload_dict = record.model_dump(mode="json")
    backend = get_backend()
    with _append_lock:
        backend.append_jsonl(partition, payload_dict)
    logger.info("audit %s slug=%s event=%s", record.request_id, slug or "-", event)
    return record


def _new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:12]}"


def ensure_meta_initialized() -> None:
    """Write ``audit/_meta.json`` once with ``schema_version`` — idempotent.

    Called at app startup. Carries the schema version once per env instead
    of per record.
    """
    backend = get_backend()
    path = storage_paths.audit_meta_path()
    if backend.exists(path):
        return
    backend.write_json_atomic(
        path,
        {
            "schema_version": 1,
            "writer_version": "inspector-v2",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
