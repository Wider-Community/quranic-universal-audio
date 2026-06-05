"""Admin Users-panel read models (Flask-free).

``list_users()`` assembles the master table from five whole-table aggregations
(``repo_admin_users``) merged in Python — no N+1 — and caches the serialized
payload on ``db_seq`` (mirrors ``public_reciters`` / ``catalog_snapshot``): any
committed write bumps ``db_seq`` so the cache self-invalidates with no
per-mutation hook. ``get_user_detail()`` is lazy, bounded, and uncached.
"""

from __future__ import annotations

from datetime import timedelta

from qua_shared.schemas import (
    Actor,
    AdminActiveClaim,
    AdminActivityEvent,
    AdminClaimEvent,
    AdminRequestEvent,
    AdminRoleEvent,
    AdminUserDetail,
    AdminUserRow,
    AdminUsersResponse,
    AdminUsersSummary,
    AdminUserStats,
    Role,
)
from services.auth import access as access_service
from services.db import _serde, repo_access, repo_admin_users
from services.db.connection import current_db_seq
from services.storage import cache

_ACTIVE_WINDOW_DAYS = 7


class LastOwnerError(Exception):
    """Raised when a role change would remove the last remaining active owner."""


def set_role(
    *,
    hf_user_id: str,
    target_role: Role,
    actor: Actor,
    login: str | None = None,
) -> dict:
    """Owner-only role change for the admin Users picker.

    Dispatches to the existing ``access_service`` mutations so authz + audit +
    durable-transaction stay centralized; ``durable_transaction`` bumps
    ``db_seq`` so the admin-users cache self-invalidates. Demote-to-contributor
    preserves the user's open claim (``cascade_release=False``) — a contributor
    is a valid claim holder, so demote is not offboarding.

    Returns a ``jsonify``-ready dict. Raises ``LastOwnerError`` /
    ``access_service.{NotAuthorized,MemberNotFound,AccessError}`` for the route
    to map to HTTP status codes.
    """
    current = Role(repo_access.resolve_role(hf_user_id))
    if current == target_role:
        return {"ok": True, "role": target_role.value, "noop": True}

    losing_owner = current == Role.OWNER and target_role != Role.OWNER
    if losing_owner and repo_access.active_owner_count() <= 1:
        raise LastOwnerError("You can't remove the last owner — promote another owner first.")

    reason = f"Role set to {target_role.value} via admin dashboard"

    if target_role == Role.CONTRIBUTOR:
        # Demote: drop the elevated role but leave any open claim intact.
        access_service.revoke(
            hf_user_id=hf_user_id,
            actor=actor,
            reason=reason,
            cascade_release=False,
        )
        return {"ok": True, "role": Role.CONTRIBUTOR.value}

    if current == Role.CONTRIBUTOR:
        member = access_service.grant(
            hf_user_id=hf_user_id,
            login=login or repo_access.get_login(hf_user_id) or hf_user_id,
            role=target_role,
            actor=actor,
            reason=reason,
        )
    else:
        # maintainer ↔ owner: in-place tier change.
        member = access_service.update(
            hf_user_id=hf_user_id,
            actor=actor,
            role=target_role,
            reason=reason,
        )
    return {"ok": True, "member": member.model_dump(mode="json")}


def list_users() -> dict:
    """Assembled admin Users payload (``AdminUsersResponse`` dump), cached on
    ``db_seq``. Returns a plain dict ready to ``jsonify``."""
    db_seq = current_db_seq()
    cached = cache.get_admin_users_cache(db_seq)
    if cached is not None:
        return cached

    base = repo_admin_users.base_rows()
    last_activity = repo_admin_users.last_activity_by_actor()
    requests_n = repo_admin_users.requests_count_by_user()
    reviews_n = repo_admin_users.reviews_count_by_actor()
    open_claims = repo_admin_users.open_claims_by_user()

    rows: list[AdminUserRow] = []
    for b in base:
        uid = b["hf_user_id"]
        claim = open_claims.get(uid)
        rows.append(
            AdminUserRow(
                hf_user_id=uid,
                login=b.get("login"),
                role=b.get("role") or "contributor",
                joined=b.get("joined"),
                last_activity=last_activity.get(uid),
                requests=requests_n.get(uid, 0),
                reviews=reviews_n.get(uid, 0),
                active_claim=AdminActiveClaim(**claim) if claim else None,
            )
        )

    cutoff = _serde.to_iso(_serde.now() - timedelta(days=_ACTIVE_WINDOW_DAYS))
    active_this_week = sum(
        1 for r in rows if r.last_activity is not None and r.last_activity >= cutoff
    )
    payload = AdminUsersResponse(
        users=rows,
        summary=AdminUsersSummary(registered=len(rows), active_this_week=active_this_week),
    ).model_dump(mode="json")

    cache.set_admin_users_cache(db_seq, payload)
    return payload


def get_user_detail(hf_user_id: str) -> dict | None:
    """Per-user detail (``AdminUserDetail`` dump), or None if no users row."""
    ident = repo_admin_users.identity(hf_user_id)
    if ident is None:
        return None

    pairs = repo_admin_users.turnaround_pairs(hf_user_id)
    avg_turnaround = _avg_turnaround_seconds(pairs)

    stats = AdminUserStats(
        reviews=repo_admin_users.reviews_count(hf_user_id),
        lifetime_claims=repo_admin_users.lifetime_claims(hf_user_id),
        avg_turnaround_seconds=avg_turnaround,
        requests_by_status=repo_admin_users.requests_by_status(hf_user_id),
    )

    role_history = [AdminRoleEvent(**r) for r in repo_admin_users.role_history(hf_user_id)]
    claims_history = [
        AdminClaimEvent(outcome=_claim_outcome(c), **c)
        for c in repo_admin_users.claims_history(hf_user_id)
    ]
    requests_history = [
        AdminRequestEvent(**r) for r in repo_admin_users.requests_history(hf_user_id)
    ]
    recent_activity = [
        AdminActivityEvent(**a) for a in repo_admin_users.recent_activity(hf_user_id)
    ]

    return AdminUserDetail(
        hf_user_id=ident["hf_user_id"],
        login=ident.get("login"),
        role=ident.get("role") or "contributor",
        joined=ident.get("joined"),
        last_login_at=ident.get("last_login_at"),
        last_entry_at=ident.get("last_entry_at"),
        last_activity=repo_admin_users.last_activity(hf_user_id),
        stats=stats,
        role_history=role_history,
        claims_history=claims_history,
        requests_history=requests_history,
        recent_activity=recent_activity,
    ).model_dump(mode="json")


def _avg_turnaround_seconds(pairs: list[tuple[str, str]]) -> float | None:
    deltas: list[float] = []
    for claimed, ready in pairs:
        cdt = _serde.from_iso(claimed)
        rdt = _serde.from_iso(ready)
        if cdt is not None and rdt is not None:
            deltas.append((rdt - cdt).total_seconds())
    return sum(deltas) / len(deltas) if deltas else None


def _claim_outcome(c: dict) -> str:
    """Mirror the mockup labels. ``close_reason`` is free-vocabulary and often
    holds the transition event name (e.g. ``reciter.published``), so match on
    substrings and fall through to a generic label."""
    if c.get("released_at") is None:
        return "claimed, open now"
    cr = c.get("close_reason") or ""
    if "published" in cr:
        return "published"
    if "force_released" in cr:
        return "force-released"
    if "reassigned" in cr:
        return "reassigned"
    if "released" in cr or c.get("marked_ready_at") is None:
        return "released without publish"
    return f"closed ({cr})" if cr else "closed"
