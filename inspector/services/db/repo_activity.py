"""Repository for activity-feed global tombstones.

A single sidecar table (``activity_tombstones``) keyed on the transition
``content_hash`` (the id the FE / activity layer already uses). The public
activity feed reader filters out rows whose content_hash appears here so
owner-only deletes apply globally without mutating the append-only audit
log.

Per-user dismissals were dropped alongside the admin notifications rail —
the Admin dashboard tabs (Reviews / Users / Requests) are the discovery
surface now, and the public feed only needs the global tombstone path.
"""

from __future__ import annotations

from datetime import datetime

from . import _serde
from .connection import get_conn
from . import repo_access


# ---- global tombstones ----


def delete(
    content_hash: str,
    *,
    deleted_by: str | None = None,
    reason: str | None = None,
    at: datetime | None = None,
) -> None:
    if deleted_by is not None:
        repo_access.ensure_user(deleted_by)
    get_conn().execute(
        "INSERT INTO activity_tombstones(audit_content_hash, deleted_by_id, reason, ts) "
        "VALUES (?,?,?,?) "
        "ON CONFLICT(audit_content_hash) DO UPDATE SET "
        "  deleted_by_id=excluded.deleted_by_id, reason=excluded.reason, ts=excluded.ts",
        (content_hash, deleted_by, reason, _serde.to_iso(at or _serde.now())),
    )


def undelete(content_hash: str) -> None:
    get_conn().execute(
        "DELETE FROM activity_tombstones WHERE audit_content_hash = ?", (content_hash,)
    )


def is_deleted(content_hash: str) -> bool:
    return get_conn().execute(
        "SELECT 1 FROM activity_tombstones WHERE audit_content_hash = ?", (content_hash,)
    ).fetchone() is not None


def deleted_set() -> set[str]:
    rows = get_conn().execute(
        "SELECT audit_content_hash FROM activity_tombstones"
    ).fetchall()
    return {r[0] for r in rows}
