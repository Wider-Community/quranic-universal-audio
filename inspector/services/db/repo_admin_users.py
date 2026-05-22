"""Raw SQL for the admin Users panel.

Two surfaces:

* **List** (``/api/admin/users``): five whole-table ``GROUP BY`` aggregations
  the service merges in Python keyed by ``hf_user_id`` — no N+1, no per-user
  query. Served indexed by ``ix_transitions_actor_ts`` / ``ix_requests_requester``
  / ``ix_claims_assignee`` (+ existing ``ix_transitions_event`` for reviews).
* **Detail** (``/api/admin/users/<id>``): per-user, ``LIMIT``-bounded queries.

All reads use ``get_conn()`` (the autocommit reader outside a txn) — no
transaction wrapper needed; WAL gives a fresh committed snapshot per SELECT.
"""

from __future__ import annotations

from .connection import get_conn

# Mark-ready transition event — "reviews" counts these per actor.
MARK_READY_EVENT = "reciter.marked_ready"

_DETAIL_HISTORY_LIMIT = 20


# ---------------------------------------------------------------------------
# list aggregations (each one query over the whole table)
# ---------------------------------------------------------------------------


def base_rows() -> list[dict]:
    """One row per user: identity + active role (else 'contributor')."""
    rows = get_conn().execute(
        "SELECT u.hf_user_id, u.login_cache AS login, u.first_seen AS joined, "
        "       COALESCE(ra.role, 'contributor') AS role "
        "FROM users u "
        "LEFT JOIN role_assignments ra "
        "  ON ra.hf_user_id = u.hf_user_id AND ra.revoked_at IS NULL"
    ).fetchall()
    return [dict(r) for r in rows]


def last_activity_by_actor() -> dict[str, str]:
    rows = get_conn().execute(
        "SELECT actor_id, MAX(ts) AS last_activity FROM transitions "
        "WHERE actor_id IS NOT NULL GROUP BY actor_id"
    ).fetchall()
    return {r["actor_id"]: r["last_activity"] for r in rows}


def requests_count_by_user() -> dict[str, int]:
    rows = get_conn().execute(
        "SELECT requester_id, COUNT(*) AS n FROM requests GROUP BY requester_id"
    ).fetchall()
    return {r["requester_id"]: r["n"] for r in rows}


def reviews_count_by_actor() -> dict[str, int]:
    rows = get_conn().execute(
        "SELECT actor_id, COUNT(*) AS n FROM transitions "
        "WHERE event = ? AND actor_id IS NOT NULL GROUP BY actor_id",
        (MARK_READY_EVENT,),
    ).fetchall()
    return {r["actor_id"]: r["n"] for r in rows}


def open_claims_by_user() -> dict[str, dict]:
    """Most-recent open claim per user (owners may hold several → take latest).

    Ordered by ``claimed_at`` ascending so the dict ends on the most recent."""
    rows = get_conn().execute(
        "SELECT c.assignee_id, c.slug, ds.state, c.marked_ready_at "
        "FROM claims c LEFT JOIN delivery_states ds ON ds.slug = c.slug "
        "WHERE c.released_at IS NULL ORDER BY c.claimed_at"
    ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        out[r["assignee_id"]] = {
            "slug": r["slug"],
            "state": r["state"],
            "marked_ready": r["marked_ready_at"] is not None,
        }
    return out


# ---------------------------------------------------------------------------
# detail (per-user, bounded)
# ---------------------------------------------------------------------------


def identity(hf_user_id: str) -> dict | None:
    row = get_conn().execute(
        "SELECT u.hf_user_id, u.login_cache AS login, u.first_seen AS joined, "
        "       u.last_login_at, u.last_entry_at, "
        "       COALESCE(ra.role, 'contributor') AS role "
        "FROM users u "
        "LEFT JOIN role_assignments ra "
        "  ON ra.hf_user_id = u.hf_user_id AND ra.revoked_at IS NULL "
        "WHERE u.hf_user_id = ?",
        (hf_user_id,),
    ).fetchone()
    return dict(row) if row else None


def reviews_count(hf_user_id: str) -> int:
    row = get_conn().execute(
        "SELECT COUNT(*) FROM transitions WHERE actor_id = ? AND event = ?",
        (hf_user_id, MARK_READY_EVENT),
    ).fetchone()
    return int(row[0]) if row else 0


def lifetime_claims(hf_user_id: str) -> int:
    row = get_conn().execute(
        "SELECT COUNT(*) FROM claims WHERE assignee_id = ?", (hf_user_id,)
    ).fetchone()
    return int(row[0]) if row else 0


def last_activity(hf_user_id: str) -> str | None:
    row = get_conn().execute(
        "SELECT MAX(ts) FROM transitions WHERE actor_id = ?", (hf_user_id,)
    ).fetchone()
    return row[0] if row and row[0] else None


def turnaround_pairs(hf_user_id: str) -> list[tuple[str, str]]:
    """(claimed_at, marked_ready_at) for claims with both set — for avg turnaround."""
    rows = get_conn().execute(
        "SELECT claimed_at, marked_ready_at FROM claims "
        "WHERE assignee_id = ? AND marked_ready_at IS NOT NULL",
        (hf_user_id,),
    ).fetchall()
    return [(r["claimed_at"], r["marked_ready_at"]) for r in rows]


def requests_by_status(hf_user_id: str) -> dict[str, int]:
    rows = get_conn().execute(
        "SELECT status, COUNT(*) AS n FROM requests WHERE requester_id = ? "
        "GROUP BY status",
        (hf_user_id,),
    ).fetchall()
    return {r["status"]: r["n"] for r in rows}


def role_history(hf_user_id: str) -> list[dict]:
    rows = get_conn().execute(
        "SELECT role, granted_at, granted_by, revoked_at, revoked_by, reason "
        "FROM role_assignments WHERE hf_user_id = ? ORDER BY granted_at DESC",
        (hf_user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def claims_history(hf_user_id: str, *, limit: int = _DETAIL_HISTORY_LIMIT) -> list[dict]:
    rows = get_conn().execute(
        "SELECT slug, claimed_at, released_at, marked_ready_at, close_reason "
        "FROM claims WHERE assignee_id = ? ORDER BY claimed_at DESC LIMIT ?",
        (hf_user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def requests_history(hf_user_id: str, *, limit: int = _DETAIL_HISTORY_LIMIT) -> list[dict]:
    rows = get_conn().execute(
        "SELECT id, kind, slug, submitted_at, status, resolved_at, resolution_reason "
        "FROM requests WHERE requester_id = ? ORDER BY submitted_at DESC LIMIT ?",
        (hf_user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def recent_activity(hf_user_id: str, *, limit: int = _DETAIL_HISTORY_LIMIT) -> list[dict]:
    rows = get_conn().execute(
        "SELECT ts, slug, event, to_state, reason FROM transitions "
        "WHERE actor_id = ? ORDER BY seq DESC LIMIT ?",
        (hf_user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]
