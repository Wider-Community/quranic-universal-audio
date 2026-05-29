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
    """Return a slug the user currently holds a *blocking* open claim on,
    else None.

    Backs the one-claim-per-non-owner check. ``marked_ready`` rows are
    EXCLUDED — once the reviewer has submitted, the row is admin-side
    until publish or send-back, so the contributor is free to claim
    something new. ``released_at IS NULL`` keeps closed claims out
    regardless of mark-ready state.

    The plural ``open_claims_for_user`` does NOT apply this filter — it's
    the role-revoke cascade target and must release every open claim
    (marked or not).
    """
    row = get_conn().execute(
        "SELECT slug FROM claims WHERE assignee_id = ? "
        "AND released_at IS NULL AND marked_ready_at IS NULL LIMIT 1",
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
    """Close the open claim for ``slug``. Returns True if one was closed.

    The mark-ready submission columns are intentionally preserved on the
    closed row so admins can audit past cycles' attestations after a
    send-back-and-re-mark. The OPEN-claim contract (next ``open_claim``
    call writes fresh values) is what gives the reviewer a clean slate.
    """
    ts = _serde.to_iso(released_at or _serde.now())
    cur = get_conn().execute(
        "UPDATE claims SET released_at = ?, close_reason = ?, closed_by_transition_id = ? "
        "WHERE slug = ? AND released_at IS NULL",
        (ts, close_reason, closed_by_transition_id, slug),
    )
    return cur.rowcount > 0


def set_marked_ready(
    slug: str,
    *,
    ready: bool,
    at: datetime | None = None,
    checklist_json: str | None = None,
    comment_checks: str = "",
    comment_issues: str = "",
    bypass_used: bool = False,
) -> None:
    """Stamp / clear ``marked_ready_at`` AND the submission columns on the
    open claim.

    When ``ready`` is True: stamps ``marked_ready_at`` and writes the
    submission columns. Callers building the submission write should
    JSON-encode the checklist via ``_serde.json_dumps``. Pass
    ``bypass_used=True`` when the submission came from a holder of the
    ``claim.mark_ready_skip_gates`` capability — ``checklist_json`` will
    typically be ``None`` in that case (the bypass path doesn't carry
    one).

    When ``ready`` is False (unmark): clears all five columns. The closed
    history row (if any) keeps its prior submission — only the OPEN
    claim is reset, mirroring how ``marked_ready_at`` already worked.
    """
    if ready:
        val = _serde.to_iso(at or _serde.now())
        get_conn().execute(
            "UPDATE claims SET marked_ready_at = ?, mark_ready_checklist = ?, "
            "mark_ready_comment_checks = ?, mark_ready_comment_issues = ?, "
            "mark_ready_bypass_used = ? "
            "WHERE slug = ? AND released_at IS NULL",
            (val, checklist_json, comment_checks, comment_issues,
             1 if bypass_used else 0, slug),
        )
    else:
        get_conn().execute(
            "UPDATE claims SET marked_ready_at = NULL, mark_ready_checklist = NULL, "
            "mark_ready_comment_checks = NULL, mark_ready_comment_issues = NULL, "
            "mark_ready_bypass_used = NULL "
            "WHERE slug = ? AND released_at IS NULL",
            (slug,),
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
