"""Rows for maintainer-uploaded alignment samples (``samples`` table).

One row per upload; the segments themselves live on the bucket under
``samples/<id>/`` and are edited through the ordinary segment save path
keyed by the ``sample--<id>`` slug. The caller owns the transaction on writes
(``durable_transaction`` at the service boundary); reads use ``get_conn()``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import _serde
from .connection import get_conn

_COLS = (
    "s.id, s.owner_hf_user_id, u.login_cache AS owner_login, s.name, s.status, s.error, "
    "s.audio_filename, s.audio_duration_ms, s.source_schema, s.pseudo_chapter, "
    "s.created_at, s.last_save_at, s.last_export_at, "
    "s.reviewed_at, s.reviewed_by, r.login_cache AS reviewed_by_login"
)
_FROM = (
    "FROM samples s LEFT JOIN users u ON u.hf_user_id = s.owner_hf_user_id "
    "LEFT JOIN users r ON r.hf_user_id = s.reviewed_by"
)


def _row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "owner_hf_user_id": row["owner_hf_user_id"],
        "owner_login": row["owner_login"],
        "name": row["name"],
        "status": row["status"],
        "error": row["error"],
        "audio_filename": row["audio_filename"],
        "audio_duration_ms": row["audio_duration_ms"],
        "source_schema": row["source_schema"],
        "pseudo_chapter": row["pseudo_chapter"],
        "created_at": row["created_at"],
        "last_save_at": row["last_save_at"],
        "last_export_at": row["last_export_at"],
        "reviewed_at": row["reviewed_at"],
        "reviewed_by": row["reviewed_by"],
        "reviewed_by_login": row["reviewed_by_login"],
    }


def create(
    *,
    sample_id: str,
    owner_hf_user_id: str,
    name: str,
    audio_filename: str,
    audio_duration_ms: int | None,
    source_schema: str,
    pseudo_chapter: int,
    at: datetime | None = None,
) -> None:
    get_conn().execute(
        "INSERT INTO samples(id, owner_hf_user_id, name, audio_filename, audio_duration_ms, "
        "source_schema, pseudo_chapter, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            sample_id,
            owner_hf_user_id,
            name,
            audio_filename,
            audio_duration_ms,
            source_schema,
            pseudo_chapter,
            _serde.to_iso(at or _serde.now()),
        ),
    )


def get(sample_id: str) -> dict[str, Any] | None:
    row = get_conn().execute(f"SELECT {_COLS} {_FROM} WHERE s.id = ?", (sample_id,)).fetchone()
    return _row_to_dict(row) if row is not None else None


def list_all() -> list[dict[str, Any]]:
    """Every sample, newest first — the samples list is shared across maintainers."""
    rows = get_conn().execute(f"SELECT {_COLS} {_FROM} ORDER BY s.created_at DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def rename(sample_id: str, name: str) -> bool:
    cur = get_conn().execute("UPDATE samples SET name = ? WHERE id = ?", (name, sample_id))
    return cur.rowcount > 0


def set_status(sample_id: str, status: str, *, error: str | None = None) -> bool:
    cur = get_conn().execute(
        "UPDATE samples SET status = ?, error = ? WHERE id = ?", (status, error, sample_id)
    )
    return cur.rowcount > 0


def touch_last_save(sample_id: str, *, at: datetime | None = None) -> bool:
    """Stamp the save time and drop any review — an edit outdates the sign-off."""
    cur = get_conn().execute(
        "UPDATE samples SET last_save_at = ?, reviewed_at = NULL, reviewed_by = NULL "
        "WHERE id = ?",
        (_serde.to_iso(at or _serde.now()), sample_id),
    )
    return cur.rowcount > 0


def set_reviewed(
    sample_id: str, *, actor_hf_user_id: str | None, at: datetime | None = None
) -> bool:
    """Mark reviewed (``actor_hf_user_id`` set) or clear the review (``None``)."""
    reviewed_at = _serde.to_iso(at or _serde.now()) if actor_hf_user_id else None
    cur = get_conn().execute(
        "UPDATE samples SET reviewed_at = ?, reviewed_by = ? WHERE id = ?",
        (reviewed_at, actor_hf_user_id, sample_id),
    )
    return cur.rowcount > 0


def touch_last_export(sample_id: str, *, at: datetime | None = None) -> bool:
    cur = get_conn().execute(
        "UPDATE samples SET last_export_at = ? WHERE id = ?",
        (_serde.to_iso(at or _serde.now()), sample_id),
    )
    return cur.rowcount > 0


def delete(sample_id: str) -> bool:
    cur = get_conn().execute("DELETE FROM samples WHERE id = ?", (sample_id,))
    return cur.rowcount > 0
