"""Email-notification subscriptions, keyed by destination email address.

One row per email — deliberately NOT keyed on the HF account, so an anonymous
visitor can subscribe. ``hf_user_id`` is an optional association set when the
saver is signed in (matches the ``request_aligned`` event to its requester).
``prefs`` is the JSON ``EmailPreferences`` blob (stored without ``email`` — the
key is the single source of truth, re-injected on read).

``manage_token`` is the stable per-subscription secret powering the one-click
unsubscribe link, the email "manage" deep-link, and an anonymous visitor's
re-fetch by token. Minted once on first save and preserved across updates.

The caller owns the transaction: writes assume an active ``durable_transaction``;
reads use ``get_conn()`` directly. Mirrors ``repo_notifications`` conventions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import _serde, repo_access
from .connection import get_conn

#: Prefs keys that an unsubscribe turns off (every event opt-in). Scope events
#: go to "off"; boolean events go to False. Kept here so unsubscribe and the
#: wire model can't drift on what "all events" means.
_SCOPE_EVENTS = ("recitation_published", "timestamps_regenerated")
_BOOL_EVENTS = (
    "request_aligned",
    "github_release",
    "riwayah_new_recitation",
    "riwayah_first_available",
    "owner_new_request",
)


def _row_to_dict(row) -> dict[str, Any]:
    prefs = _serde.json_loads(row["prefs"]) or {}
    prefs["email"] = row["email"]  # key is canonical
    return {
        "email": row["email"],
        "hf_user_id": row["hf_user_id"],
        "prefs": prefs,
        "manage_token": row["manage_token"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _prefs_for_storage(prefs: dict[str, Any]) -> dict[str, Any]:
    """Strip ``email`` before persisting — the column is the source of truth."""
    return {k: v for k, v in prefs.items() if k != "email"}


def get_by_email(email: str) -> dict[str, Any] | None:
    row = (
        get_conn()
        .execute("SELECT * FROM email_subscriptions WHERE email = ?", (normalize_email(email),))
        .fetchone()
    )
    return _row_to_dict(row) if row else None


def get_by_hf_user(hf_user_id: str) -> dict[str, Any] | None:
    """Most-recently-updated subscription associated with a signed-in user."""
    row = (
        get_conn()
        .execute(
            "SELECT * FROM email_subscriptions WHERE hf_user_id = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (hf_user_id,),
        )
        .fetchone()
    )
    return _row_to_dict(row) if row else None


def get_by_token(token: str) -> dict[str, Any] | None:
    row = (
        get_conn()
        .execute("SELECT * FROM email_subscriptions WHERE manage_token = ?", (token,))
        .fetchone()
    )
    return _row_to_dict(row) if row else None


def all_subscriptions() -> list[dict[str, Any]]:
    """Every subscription row (the emitter filters per event in Python — the
    subscriber set is small, so a full scan beats event-shaped SQL)."""
    rows = get_conn().execute("SELECT * FROM email_subscriptions").fetchall()
    return [_row_to_dict(r) for r in rows]


def upsert(
    *,
    email: str,
    hf_user_id: str | None,
    prefs: dict[str, Any],
    new_token: str,
    at: datetime | None = None,
) -> dict[str, Any]:
    """Insert or update the subscription for ``email``.

    On a fresh row, ``new_token`` becomes the ``manage_token``; on conflict the
    existing token + ``created_at`` are preserved and only ``prefs`` /
    ``hf_user_id`` / ``updated_at`` are refreshed. Returns the stored row dict.
    """
    key = normalize_email(email)
    if hf_user_id:
        repo_access.ensure_user(hf_user_id)
    ts = _serde.to_iso(at or _serde.now())
    blob = _serde.json_dumps(_prefs_for_storage(prefs))
    get_conn().execute(
        "INSERT INTO email_subscriptions"
        "(email, hf_user_id, prefs, manage_token, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(email) DO UPDATE SET "
        "  hf_user_id = excluded.hf_user_id, "
        "  prefs = excluded.prefs, "
        "  updated_at = excluded.updated_at",
        (key, hf_user_id, blob, new_token, ts, ts),
    )
    row = get_by_email(key)
    assert row is not None  # just inserted/updated
    return row


def unsubscribe_by_token(token: str, *, at: datetime | None = None) -> dict[str, Any] | None:
    """Turn every event opt-in off for the subscription owning ``token``.

    Keeps the row + token so the same link can re-manage. Returns the updated row
    dict, or ``None`` when the token is unknown.
    """
    existing = get_by_token(token)
    if existing is None:
        return None
    prefs = dict(existing["prefs"])
    for k in _SCOPE_EVENTS:
        prefs[k] = "off"
    for k in _BOOL_EVENTS:
        prefs[k] = False
    ts = _serde.to_iso(at or _serde.now())
    get_conn().execute(
        "UPDATE email_subscriptions SET prefs = ?, updated_at = ? WHERE manage_token = ?",
        (_serde.json_dumps(_prefs_for_storage(prefs)), ts, token),
    )
    return get_by_token(token)
