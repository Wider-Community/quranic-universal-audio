"""Global announcement rows for the Dashboard "My Notifications" rail.

Unlike ``repo_notifications`` (one materialized row per target user), an
announcement is a SINGLE global row composed by an owner and shown to everyone —
signed-in or anonymous — via the public read route. Dismiss/seen state lives in
the browser (localStorage), so there is no per-user state here. An announcement
is active until an owner revokes it (``revoked_at`` set; the row is retained for
the admin audit list).

The caller owns the transaction: writes assume an active ``transaction()`` (the
service's ``durable_transaction``). Reads use ``get_conn()`` directly. Mirrors
``repo_notifications`` conventions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import _serde
from .connection import get_conn

_COLS = "id, title, body, author_hf_user_id, author_login, created_at, revoked_at"


def _row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "author_login": row["author_login"],
        "created_at": row["created_at"],
        "revoked_at": row["revoked_at"],
    }


def create(
    *,
    title: str,
    body: str | None,
    author_hf_user_id: str,
    author_login: str | None,
    at: datetime | None = None,
) -> int:
    """Insert one announcement. Returns the new rowid."""
    cur = get_conn().execute(
        "INSERT INTO announcements"
        "(title, body, author_hf_user_id, author_login, created_at) "
        "VALUES (?,?,?,?,?)",
        (title, body, author_hf_user_id, author_login, _serde.to_iso(at or _serde.now())),
    )
    rowid = cur.lastrowid
    if rowid is None:
        raise RuntimeError("INSERT did not produce a rowid")
    return rowid


def list_active(*, limit: int = 50) -> list[dict[str, Any]]:
    """Newest-first active (un-revoked) announcements."""
    rows = (
        get_conn()
        .execute(
            f"SELECT {_COLS} FROM announcements "
            "WHERE revoked_at IS NULL ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        )
        .fetchall()
    )
    return [_row_to_dict(r) for r in rows]


def list_all(*, limit: int = 200) -> list[dict[str, Any]]:
    """Newest-first announcements, active + revoked (admin management list)."""
    rows = (
        get_conn()
        .execute(
            f"SELECT {_COLS} FROM announcements ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        )
        .fetchall()
    )
    return [_row_to_dict(r) for r in rows]


def revoke(announcement_id: int, *, at: datetime | None = None) -> bool:
    """Stamp ``revoked_at`` on one active announcement. Returns False if the id
    doesn't exist or was already revoked."""
    cur = get_conn().execute(
        "UPDATE announcements SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
        (_serde.to_iso(at or _serde.now()), announcement_id),
    )
    return cur.rowcount > 0
