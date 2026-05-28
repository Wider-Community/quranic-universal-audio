"""Repository for activity sidecars: per-user dismissals + global tombstones.

Both reference the transition ``content_hash`` (the id the FE/activity layer
already uses), so the feed read path filters dismissed/deleted entries with a
join/lookup on that key. Replaces ``activity/state.json``.
"""

from __future__ import annotations

from datetime import datetime

from . import _serde
from .connection import get_conn
from . import repo_access


# ---- per-user dismissals ----


def dismiss(content_hash: str, hf_user_id: str, *, at: datetime | None = None) -> None:
    repo_access.ensure_user(hf_user_id)
    get_conn().execute(
        "INSERT OR IGNORE INTO activity_dismissals(audit_content_hash, hf_user_id, ts) "
        "VALUES (?,?,?)",
        (content_hash, hf_user_id, _serde.to_iso(at or _serde.now())),
    )


def undismiss(content_hash: str, hf_user_id: str) -> None:
    get_conn().execute(
        "DELETE FROM activity_dismissals WHERE audit_content_hash = ? AND hf_user_id = ?",
        (content_hash, hf_user_id),
    )


def is_dismissed(content_hash: str, hf_user_id: str) -> bool:
    return get_conn().execute(
        "SELECT 1 FROM activity_dismissals WHERE audit_content_hash = ? AND hf_user_id = ?",
        (content_hash, hf_user_id),
    ).fetchone() is not None


def dismissed_for_user(hf_user_id: str) -> set[str]:
    rows = get_conn().execute(
        "SELECT audit_content_hash FROM activity_dismissals WHERE hf_user_id = ?",
        (hf_user_id,),
    ).fetchall()
    return {r[0] for r in rows}


def all_dismissals() -> dict[str, list[str]]:
    """Every per-user dismissal as ``{hf_user_id: [content_hash, ...]}`` — backs
    the legacy ``activity_state.snapshot().dismissals`` reassembly."""
    rows = get_conn().execute(
        "SELECT hf_user_id, audit_content_hash FROM activity_dismissals ORDER BY ts"
    ).fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["hf_user_id"], []).append(r["audit_content_hash"])
    return out


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
