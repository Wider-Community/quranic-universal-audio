"""Repository for ``users`` + ``role_assignments``.

Reconstructs the legacy ``Member`` / ``RolesFile`` shapes so the access
service + ``/api/admin/access`` listing keep their wire contract. Write
primitives operate on the active transaction connection (the service layer
wraps grant/revoke/update in ``transaction()`` and pairs each with a
``repo_transitions.append``); the partial-unique index
``ux_role_active`` enforces "one active role per user".
"""

from __future__ import annotations

from datetime import datetime

from scripts.lib.schemas import Member, Role, RolesFile

from . import _serde
from .connection import get_conn


# ---- users ----


def ensure_user(
    hf_user_id: str,
    *,
    login: str | None = None,
    now: datetime | None = None,
) -> None:
    """Upsert a users row; refresh login_cache + last_seen (and first_seen once)."""
    conn = get_conn()
    ts = _serde.to_iso(now or _serde.now())
    conn.execute(
        "INSERT INTO users(hf_user_id, login_cache, first_seen, last_seen) "
        "VALUES (?,?,?,?) "
        "ON CONFLICT(hf_user_id) DO UPDATE SET "
        "  login_cache = COALESCE(excluded.login_cache, users.login_cache), "
        "  last_seen = excluded.last_seen",
        (hf_user_id, login, ts, ts),
    )


def get_login(hf_user_id: str) -> str | None:
    row = get_conn().execute(
        "SELECT login_cache FROM users WHERE hf_user_id = ?", (hf_user_id,)
    ).fetchone()
    return row[0] if row else None


# ---- role queries ----


def resolve_role(hf_user_id: str) -> Role:
    row = get_conn().execute(
        "SELECT role FROM role_assignments WHERE hf_user_id = ? AND revoked_at IS NULL",
        (hf_user_id,),
    ).fetchone()
    return Role(row[0]) if row else Role.CONTRIBUTOR


def _member_from_rows(ra, login: str | None) -> Member:
    return Member(
        hf_user_id=ra["hf_user_id"],
        login=login or ra["hf_user_id"],
        role=Role(ra["role"]),
        added_at=_serde.from_iso(ra["granted_at"]),
        added_by_hf_id=ra["granted_by"] or "unknown",
        removed_at=_serde.from_iso(ra["revoked_at"]),
        removed_by_hf_id=ra["revoked_by"],
    )


def find_member(hf_user_id: str) -> Member | None:
    """Active member (active role_assignment joined to users), or None."""
    row = get_conn().execute(
        "SELECT ra.*, u.login_cache AS login FROM role_assignments ra "
        "LEFT JOIN users u ON u.hf_user_id = ra.hf_user_id "
        "WHERE ra.hf_user_id = ? AND ra.revoked_at IS NULL",
        (hf_user_id,),
    ).fetchone()
    return _member_from_rows(row, row["login"]) if row else None


def active_members() -> list[Member]:
    rows = get_conn().execute(
        "SELECT ra.*, u.login_cache AS login FROM role_assignments ra "
        "LEFT JOIN users u ON u.hf_user_id = ra.hf_user_id "
        "WHERE ra.revoked_at IS NULL ORDER BY ra.granted_at"
    ).fetchall()
    return [_member_from_rows(r, r["login"]) for r in rows]


def snapshot() -> RolesFile:
    """All assignments (active + revoked) as a RolesFile — parity with the
    legacy in-memory store that kept soft-deleted members queryable."""
    rows = get_conn().execute(
        "SELECT ra.*, u.login_cache AS login FROM role_assignments ra "
        "LEFT JOIN users u ON u.hf_user_id = ra.hf_user_id "
        "ORDER BY ra.granted_at"
    ).fetchall()
    return RolesFile(members=[_member_from_rows(r, r["login"]) for r in rows])


# ---- role mutations (caller owns the transaction) ----


def grant_role(
    *,
    hf_user_id: str,
    login: str,
    role: Role,
    granted_by: str,
    now: datetime | None = None,
) -> Member:
    ts = now or _serde.now()
    ensure_user(hf_user_id, login=login, now=ts)
    ensure_user(granted_by, now=ts)  # granter FK target must exist
    conn = get_conn()
    conn.execute(
        "INSERT INTO role_assignments(hf_user_id, role, granted_at, granted_by) "
        "VALUES (?,?,?,?)",
        (hf_user_id, role.value, _serde.to_iso(ts), granted_by),
    )
    member = find_member(hf_user_id)
    if member is None:  # the row was just inserted; this should never happen
        raise RuntimeError(f"grant_role: member {hf_user_id!r} missing after insert")
    return member


def has_any_active() -> bool:
    """True iff any active role assignment exists (bootstrap guard)."""
    return get_conn().execute(
        "SELECT 1 FROM role_assignments WHERE revoked_at IS NULL LIMIT 1"
    ).fetchone() is not None


def revoke_role(
    *,
    hf_user_id: str,
    revoked_by: str,
    reason: str | None = None,
    now: datetime | None = None,
) -> Member | None:
    """Soft-revoke the active role. Returns the (now-revoked) Member, or None
    if the user had no active role."""
    member = find_member(hf_user_id)
    if member is None:
        return None
    ensure_user(revoked_by, now=now)  # revoker FK target must exist
    ts = _serde.to_iso(now or _serde.now())
    get_conn().execute(
        "UPDATE role_assignments SET revoked_at = ?, revoked_by = ?, reason = ? "
        "WHERE hf_user_id = ? AND revoked_at IS NULL",
        (ts, revoked_by, reason, hf_user_id),
    )
    member.removed_at = _serde.from_iso(ts)
    member.removed_by_hf_id = revoked_by
    return member


def update_role(
    *,
    hf_user_id: str,
    login: str | None = None,
    role: Role | None = None,
) -> Member | None:
    """Refresh login cache and/or change the active role tier in place."""
    member = find_member(hf_user_id)
    if member is None:
        return None
    conn = get_conn()
    if login is not None:
        conn.execute(
            "UPDATE users SET login_cache = ? WHERE hf_user_id = ?", (login, hf_user_id)
        )
    if role is not None:
        conn.execute(
            "UPDATE role_assignments SET role = ? WHERE hf_user_id = ? AND revoked_at IS NULL",
            (role.value, hf_user_id),
        )
    return find_member(hf_user_id)
