"""Email digest buffer — one row per (recipient × event_kind × reciter).

The two high-volume email events (`recitation_published`, `timestamps_regenerated`)
buffer a row here per matched recipient instead of sending immediately; a
background sweep (`services.email.digest`) flushes each (email, event_kind) group
as a single batched email once its window ages past the digest window. Rows are
deleted on flush.

`manage_token` + `reciter_name` are captured at buffer time so the flush renders
without re-resolving subscriptions. `reciter_id` dedups a reciter buffered twice
within one window.

The caller owns the transaction: writes assume an active ``durable_transaction``;
reads use ``get_conn()`` directly. Mirrors ``repo_email_subscriptions``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import _serde
from .connection import get_conn


def add(
    *,
    email: str,
    manage_token: str,
    event_kind: str,
    reciter_id: str,
    reciter_name: str,
    at: datetime | None = None,
) -> None:
    """Buffer one event for one recipient. Assumes an active transaction."""
    ts = _serde.to_iso(at or _serde.now())
    get_conn().execute(
        "INSERT INTO email_digest"
        "(email, manage_token, event_kind, reciter_id, reciter_name, buffered_at) "
        "VALUES (?,?,?,?,?,?)",
        (email.strip().lower(), manage_token, event_kind, reciter_id, reciter_name, ts),
    )


def due_groups(*, cutoff: datetime) -> list[dict[str, str]]:
    """(email, event_kind) groups whose EARLIEST buffered row is at/under
    ``cutoff`` — i.e. the tumbling window opened that long ago and is due to
    flush. ``cutoff`` is ``now - window``."""
    rows = (
        get_conn()
        .execute(
            "SELECT email, event_kind FROM email_digest "
            "GROUP BY email, event_kind HAVING MIN(buffered_at) <= ? "
            "ORDER BY MIN(buffered_at)",
            (_serde.to_iso(cutoff),),
        )
        .fetchall()
    )
    return [{"email": r["email"], "event_kind": r["event_kind"]} for r in rows]


def items_for(email: str, event_kind: str) -> list[dict[str, Any]]:
    """All buffered rows for one group, oldest first (the flush dedups by
    ``reciter_id`` preserving this first-seen order)."""
    rows = (
        get_conn()
        .execute(
            "SELECT id, manage_token, reciter_id, reciter_name, buffered_at "
            "FROM email_digest WHERE email = ? AND event_kind = ? ORDER BY buffered_at, id",
            (email.strip().lower(), event_kind),
        )
        .fetchall()
    )
    return [
        {
            "id": r["id"],
            "manage_token": r["manage_token"],
            "reciter_id": r["reciter_id"],
            "reciter_name": r["reciter_name"],
            "buffered_at": r["buffered_at"],
        }
        for r in rows
    ]


def delete_ids(ids: list[int]) -> None:
    """Delete the exact rows that were flushed (by id) — NOT the whole group, so
    an event buffered after the flush read survives. Assumes an active transaction."""
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    get_conn().execute(f"DELETE FROM email_digest WHERE id IN ({placeholders})", ids)
