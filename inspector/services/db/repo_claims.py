"""Repository for the ``claims`` table (current + history).

The open claim for a slug is the source of truth for ``assignee_*`` and
``marked_ready`` on the assembled ``ReciterRow`` (see ``repo_state``). One
open claim per slug is enforced by the partial-unique index
``ux_claim_open_slug``; one-open-claim-per-non-owner is enforced in the
transition layer (owners are exempt by policy) via ``open_claim_for_user``.
"""

from __future__ import annotations

from datetime import datetime

from . import _serde
from .connection import get_conn


def get_open_claim(slug: str):
    return get_conn().execute(
        "SELECT * FROM claims WHERE slug = ? AND released_at IS NULL", (slug,)
    ).fetchone()


def open_claim_for_user(assignee_id: str) -> str | None:
    """Return a slug the user currently holds an open claim on, else None.
    Backs the one-claim-per-non-owner check (an O(1) index lookup, replacing
    the old all_rows() scan)."""
    row = get_conn().execute(
        "SELECT slug FROM claims WHERE assignee_id = ? AND released_at IS NULL LIMIT 1",
        (assignee_id,),
    ).fetchone()
    return row[0] if row else None


def open_claims_for_user(assignee_id: str) -> list[str]:
    rows = get_conn().execute(
        "SELECT slug FROM claims WHERE assignee_id = ? AND released_at IS NULL "
        "ORDER BY claimed_at",
        (assignee_id,),
    ).fetchall()
    return [r[0] for r in rows]


def open_claim(
    *,
    slug: str,
    assignee_id: str,
    assignee_login: str | None,
    claimed_at: datetime | None = None,
    opened_by_transition_id: str | None = None,
) -> int:
    """Open a new claim. Raises sqlite3.IntegrityError if one is already open
    for this slug. Returns the new claim id."""
    ts = _serde.to_iso(claimed_at or _serde.now())
    cur = get_conn().execute(
        "INSERT INTO claims(slug, assignee_id, assignee_login_snapshot, claimed_at, "
        "opened_by_transition_id) VALUES (?,?,?,?,?)",
        (slug, assignee_id, assignee_login, ts, opened_by_transition_id),
    )
    return int(cur.lastrowid)


def close_claim(
    *,
    slug: str,
    close_reason: str,
    released_at: datetime | None = None,
    closed_by_transition_id: str | None = None,
) -> bool:
    """Close the open claim for ``slug``. Returns True if one was closed."""
    ts = _serde.to_iso(released_at or _serde.now())
    cur = get_conn().execute(
        "UPDATE claims SET released_at = ?, close_reason = ?, closed_by_transition_id = ? "
        "WHERE slug = ? AND released_at IS NULL",
        (ts, close_reason, closed_by_transition_id, slug),
    )
    return cur.rowcount > 0


def set_marked_ready(slug: str, *, ready: bool, at: datetime | None = None) -> None:
    """Stamp / clear marked_ready_at on the open claim."""
    val = _serde.to_iso(at or _serde.now()) if ready else None
    get_conn().execute(
        "UPDATE claims SET marked_ready_at = ? WHERE slug = ? AND released_at IS NULL",
        (val, slug),
    )


def reassign(
    *,
    slug: str,
    new_assignee_id: str,
    new_assignee_login: str | None,
    at: datetime | None = None,
    closed_by_transition_id: str | None = None,
    opened_by_transition_id: str | None = None,
) -> int:
    """Close the current open claim (reason='reassigned') and open a new one,
    preserving history. Returns the new claim id."""
    ts = at or _serde.now()
    close_claim(
        slug=slug,
        close_reason="reassigned",
        released_at=ts,
        closed_by_transition_id=closed_by_transition_id,
    )
    return open_claim(
        slug=slug,
        assignee_id=new_assignee_id,
        assignee_login=new_assignee_login,
        claimed_at=ts,
        opened_by_transition_id=opened_by_transition_id,
    )
