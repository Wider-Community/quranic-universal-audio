"""Repository for destructive recitation purge bookkeeping.

All writes require the caller's active durable transaction. The row is retained
after completion so admin projections can distinguish destructive purges from
legacy visibility-only discards and Undiscard can never imply data restoration.
"""

from __future__ import annotations

from datetime import UTC, datetime

from . import _serde
from .connection import get_conn


def get(slug: str) -> dict | None:
    row = (
        get_conn()
        .execute("SELECT * FROM recitation_discard_cleanup WHERE slug = ?", (slug,))
        .fetchone()
    )
    return dict(row) if row else None


def begin(*, slug: str, requested_by: str, reason: str) -> None:
    now = _serde.to_iso(datetime.now(UTC))
    get_conn().execute(
        "INSERT INTO recitation_discard_cleanup "
        "(slug, status, requested_at, requested_by, reason, completed_at, last_error) "
        "VALUES (?, 'pending', ?, ?, ?, NULL, NULL) "
        "ON CONFLICT(slug) DO UPDATE SET "
        "status = 'pending', requested_at = excluded.requested_at, "
        "requested_by = excluded.requested_by, reason = excluded.reason, "
        "completed_at = NULL, last_error = NULL",
        (slug, now, requested_by, reason),
    )


def mark_failed(slug: str, error: str) -> None:
    get_conn().execute(
        "UPDATE recitation_discard_cleanup SET status = 'failed', "
        "completed_at = NULL, last_error = ? WHERE slug = ?",
        (error[:2000], slug),
    )


def mark_completed(slug: str) -> None:
    now = _serde.to_iso(datetime.now(UTC))
    get_conn().execute(
        "UPDATE recitation_discard_cleanup SET status = 'completed', "
        "completed_at = ?, last_error = NULL WHERE slug = ?",
        (now, slug),
    )


def mark_restored(slug: str) -> None:
    get_conn().execute(
        "UPDATE recitation_discard_cleanup SET status = 'restored', "
        "last_error = NULL WHERE slug = ?",
        (slug,),
    )
