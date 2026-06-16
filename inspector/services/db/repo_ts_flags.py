"""Public verse-level flags on the Timestamps tab.

One row per ``(slug, verse_key, identity)`` — identity being EITHER a signed-in
``hf_user_id`` OR an anonymous browser ``anon_token`` (exactly one is set).
Multiple users flag the same verse, so a verse accumulates multiple comments;
re-flagging the same verse as the same identity upserts the comment in place.

The caller owns the transaction: writes assume an active ``durable_transaction``;
reads use ``get_conn()`` directly. ``repo_access.ensure_user`` keeps the nullable
FK valid for signed-in flags. Mirrors ``repo_email_subscriptions`` conventions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import _serde, repo_access
from .connection import get_conn


def _row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "slug": row["slug"],
        "verse_key": row["verse_key"],
        "hf_user_id": row["hf_user_id"],
        "anon_token": row["anon_token"],
        "login_at_time": row["login_at_time"],
        "role_at_time": row["role_at_time"],
        "comment": row["comment"],
        "created_at": _serde.from_iso(row["created_at"]),
        "updated_at": _serde.from_iso(row["updated_at"]),
    }


# --- reads -----------------------------------------------------------------


def verse_counts(slug: str) -> list[dict[str, Any]]:
    """Per-verse flag counts for a reciter, ordered by verse. Feeds the
    "Flagged issues" accordion (verse pills + a count badge)."""
    rows = (
        get_conn()
        .execute(
            "SELECT verse_key, COUNT(*) AS count FROM ts_verse_flags "
            "WHERE slug = ? GROUP BY verse_key ORDER BY verse_key",
            (slug,),
        )
        .fetchall()
    )
    return [{"verse_key": r["verse_key"], "count": r["count"]} for r in rows]


def list_for_verse(slug: str, verse_key: str) -> list[dict[str, Any]]:
    """Every comment for a verse (all identities), oldest first. Feeds the
    flag modal."""
    rows = (
        get_conn()
        .execute(
            "SELECT * FROM ts_verse_flags WHERE slug = ? AND verse_key = ? ORDER BY created_at",
            (slug, verse_key),
        )
        .fetchall()
    )
    return [_row_to_dict(r) for r in rows]


# --- writes (caller owns the durable_transaction) --------------------------


def upsert_flag(
    *,
    slug: str,
    verse_key: str,
    hf_user_id: str | None,
    anon_token: str | None,
    login_at_time: str | None,
    role_at_time: str | None,
    comment: str | None,
    at: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    """Insert or update the caller's flag on ``(slug, verse_key)``.

    Keyed by ``hf_user_id`` when signed in, else by ``anon_token``. On conflict
    only ``comment`` + ``updated_at`` are refreshed. Returns ``(row, created)``
    where ``created`` is True when this inserted a new flag (drives the
    notify-on-new-comment decision). Exactly one of ``hf_user_id`` /
    ``anon_token`` must be set.
    """
    if (hf_user_id is None) == (anon_token is None):
        raise ValueError("exactly one of hf_user_id / anon_token must be set")
    if hf_user_id is not None:
        repo_access.ensure_user(hf_user_id)
    # Uniqueness is enforced by a PARTIAL index per identity column, so the
    # ON CONFLICT target must echo the index's WHERE predicate to match it.
    conflict_col = "hf_user_id" if hf_user_id is not None else "anon_token"
    created = _current(slug, verse_key, hf_user_id, anon_token) is None
    ts = _serde.to_iso(at or _serde.now())
    get_conn().execute(
        "INSERT INTO ts_verse_flags"
        "(slug, verse_key, hf_user_id, anon_token, login_at_time, role_at_time, "
        " comment, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?) "
        f"ON CONFLICT(slug, verse_key, {conflict_col}) WHERE {conflict_col} IS NOT NULL "
        "DO UPDATE SET comment = excluded.comment, updated_at = excluded.updated_at",
        (slug, verse_key, hf_user_id, anon_token, login_at_time, role_at_time, comment, ts, ts),
    )
    row = _current(slug, verse_key, hf_user_id, anon_token)
    assert row is not None  # just inserted/updated
    return row, created


def delete_flag(
    *,
    slug: str,
    verse_key: str,
    hf_user_id: str | None,
    anon_token: str | None,
) -> bool:
    """Delete the caller's own flag. Returns True when a row was removed."""
    if (hf_user_id is None) == (anon_token is None):
        raise ValueError("exactly one of hf_user_id / anon_token must be set")
    col = "hf_user_id" if hf_user_id is not None else "anon_token"
    val = hf_user_id if hf_user_id is not None else anon_token
    cur = get_conn().execute(
        f"DELETE FROM ts_verse_flags WHERE slug = ? AND verse_key = ? AND {col} = ?",
        (slug, verse_key, val),
    )
    return cur.rowcount > 0


def _current(
    slug: str, verse_key: str, hf_user_id: str | None, anon_token: str | None
) -> dict[str, Any] | None:
    col = "hf_user_id" if hf_user_id is not None else "anon_token"
    val = hf_user_id if hf_user_id is not None else anon_token
    row = (
        get_conn()
        .execute(
            f"SELECT * FROM ts_verse_flags WHERE slug = ? AND verse_key = ? AND {col} = ?",
            (slug, verse_key, val),
        )
        .fetchone()
    )
    return _row_to_dict(row) if row else None
