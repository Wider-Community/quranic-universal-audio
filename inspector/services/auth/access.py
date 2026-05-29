"""Roles service: facade over SQLite ``users`` + ``role_assignments`` tables.

Inspector backend is sole writer. ``resolve_role`` / ``find_member`` /
``snapshot`` read the assembled ``Member``/``RolesFile`` shapes; grant / revoke
/ update each run in one durable transaction paired with an ``access.*``
transition row.

Revoke is atomic with its cascade: revoking a user who holds open claims closes
those claims AND emits their ``reciter.released`` transitions in the SAME
transaction (via the non-locking ``state._apply_event``) — no more "role
revoked but a claim left open".

Spec: docs/planning/inspector-deploy/v2/inspector-state-management.md §9.
"""

from __future__ import annotations

import logging

from scripts.lib.schemas import Actor, Member, Role, RolesFile

from . import permissions
from services.state import audit
from services.db import repo_access, repo_claims
from services.db import sync as _sync

logger = logging.getLogger(__name__)


# ---- Errors ----


class AccessError(Exception):
    pass


class NotAuthorized(AccessError):
    pass


class MemberNotFound(AccessError):
    pass


class MemberAlreadyActive(AccessError):
    pass


# ---- Boot / reads ----


def hydrate() -> None:
    """No-op under the SQLite substrate (DB is the source of truth)."""
    return None


def snapshot() -> RolesFile:
    return repo_access.snapshot()


def resolve_role(hf_user_id: str) -> Role:
    """Effective role for ``hf_user_id``. Non-members → CONTRIBUTOR."""
    return repo_access.resolve_role(hf_user_id)


def find_member(hf_user_id: str) -> Member | None:
    return repo_access.find_member(hf_user_id)


# ---- Authorization ----


def _require_role(actor: Actor, *allowed: Role) -> None:
    if not permissions.has_role(actor, *allowed):
        raise NotAuthorized(
            f"actor role {actor.role!r} cannot perform this action; "
            f"requires {[r.value for r in allowed]}"
        )


def _require_capability(actor: Actor, capability: str) -> None:
    """Capability gate raising ``NotAuthorized`` (the access-layer error
    contract). Data-driven successor to ``_require_role`` so role mutation is
    governed by ``roles.assign_maintainer`` / ``roles.assign_owner`` and the
    picker + ``/api/admin/access/*`` endpoints enforce the SAME capabilities.
    The structural owner-on-owner asymmetry below is NOT a capability — it
    stays enforced regardless of any toggle. Lazy import avoids the
    access↔capabilities import cycle at package init."""
    from . import capabilities as _capabilities

    if not _capabilities.can(actor, capability):
        raise NotAuthorized(
            f"actor role {actor.role!r} lacks capability {capability!r}"
        )


# ---- Mutations ----


def grant(
    *,
    hf_user_id: str,
    login: str,
    role: Role,
    actor: Actor,
    reason: str | None = None,
) -> Member:
    """Add a new member. Granting OWNER requires OWNER; MAINTAINER requires
    MAINTAINER+."""
    if role == Role.CONTRIBUTOR:
        raise AccessError("CONTRIBUTOR is implicit; do not grant it explicitly")
    if role == Role.OWNER:
        _require_capability(actor, "roles.assign_owner")
    else:
        _require_capability(actor, "roles.assign_maintainer")

    with _sync.durable_transaction():
        existing = repo_access.find_member(hf_user_id)
        if existing is not None:
            raise MemberAlreadyActive(
                f"member {hf_user_id} already active with role {existing.role}"
            )
        member = repo_access.grant_role(
            hf_user_id=hf_user_id, login=login, role=role, granted_by=actor.hf_user_id,
        )
        audit.append(
            event="access.role_granted",
            actor=actor,
            payload={
                "target_hf_user_id": hf_user_id,
                "target_login": login,
                "role": role.value,
            },
            reason=reason,
        )
    return member


def revoke(
    *,
    hf_user_id: str,
    actor: Actor,
    reason: str | None = None,
    cascade_release: bool = True,
) -> tuple[Member, list[str]]:
    """Soft-revoke a member AND (by default) release every open claim they hold,
    atomically.

    Returns ``(revoked_member, released_slugs)``. With ``cascade_release=True``
    (offboarding — the ``/api/admin/access/revoke`` endpoint) the cascade emits
    one ``reciter.released`` transition per slug (via ``state._apply_event`` — no
    slug lock, so no deadlock against the write lock) and closes the claim +
    flips the delivery back to AWAITING_REVIEW, all in the same transaction as
    the role revoke. Either everything commits or nothing does.

    With ``cascade_release=False`` (a role-picker *demote* to contributor) the
    claims are left untouched: a contributor is a valid claim holder, so a
    demoted reviewer keeps their work-in-progress. Only the role assignment is
    dropped + audited."""
    _require_capability(actor, "roles.assign_maintainer")
    # Lazy import: avoids a state↔access import cycle at package init.
    from services.state import state as _state_service

    with _sync.durable_transaction() as conn:
        target = repo_access.find_member(hf_user_id)
        if target is None:
            raise MemberNotFound(hf_user_id)
        if permissions.is_owner(target) and not permissions.is_owner(actor):
            raise NotAuthorized("only OWNER can revoke an OWNER member")

        released_slugs: list[str] = []
        if cascade_release:
            for slug in repo_claims.open_claims_for_user(hf_user_id):
                _state_service._apply_event(
                    conn,
                    slug,
                    "reciter.released",
                    actor=actor,
                    payload={},
                    reason=f"Auto-release: role revoked. {reason}" if reason else "Auto-release: role revoked.",
                )
                released_slugs.append(slug)

        member = repo_access.revoke_role(
            hf_user_id=hf_user_id, revoked_by=actor.hf_user_id, reason=reason,
        )
        audit.append(
            event="access.role_revoked",
            actor=actor,
            payload={
                "target_hf_user_id": hf_user_id,
                "target_login": target.login,
                "role": target.role.value if hasattr(target.role, "value") else target.role,
            },
            reason=reason,
        )
    return (member or target), released_slugs


def update(
    *,
    hf_user_id: str,
    actor: Actor,
    login: str | None = None,
    role: Role | None = None,
    reason: str | None = None,
) -> Member:
    """Refresh login cache or change role tier on an active member."""
    _require_capability(actor, "roles.assign_maintainer")
    if role == Role.OWNER:
        _require_capability(actor, "roles.assign_owner")

    with _sync.durable_transaction():
        target = repo_access.find_member(hf_user_id)
        if target is None:
            raise MemberNotFound(hf_user_id)
        if permissions.is_owner(target) and not permissions.is_owner(actor):
            raise NotAuthorized("only OWNER can edit an OWNER member")

        patch: dict = {}
        if login is not None and login != target.login:
            patch["login"] = {"from": target.login, "to": login}
        cur_role = Role(target.role) if not isinstance(target.role, Role) else target.role
        if role is not None and cur_role != role:
            patch["role"] = {"from": cur_role.value, "to": role.value}
        updated = repo_access.update_role(hf_user_id=hf_user_id, login=login, role=role)
        audit.append(
            event="access.role_updated",
            actor=actor,
            payload={"target_hf_user_id": hf_user_id, "patch": patch},
            reason=reason,
        )
    return updated or target


# ---- Bootstrap (one-shot CLI) ----


def bootstrap(hf_user_id: str, login: str) -> Member:
    """Seed the first OWNER into an empty roles table. Raises if any active
    member already exists."""
    with _sync.durable_transaction():
        if repo_access.has_any_active():
            raise AccessError(
                "bootstrap refused: an active member already exists. "
                "Use grant() with an authenticated owner instead."
            )
        member = repo_access.grant_role(
            hf_user_id=hf_user_id, login=login, role=Role.OWNER, granted_by="bootstrap",
        )
        audit.append(
            event="access.role_granted",
            actor=Actor(hf_user_id="bootstrap", login_at_time="bootstrap", role=Role.OWNER),
            payload={
                "target_hf_user_id": hf_user_id,
                "target_login": login,
                "role": Role.OWNER.value,
            },
            reason="phase-1 bootstrap",
        )
    return member


# ---- CLI entry point ----


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="inspector.services.access")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    boot = subparsers.add_parser("bootstrap", help="Seed the first OWNER")
    boot.add_argument("--hf-user-id", required=True)
    boot.add_argument("--login", required=True)

    subparsers.add_parser("show", help="Print active members")

    args = parser.parse_args(argv)
    if args.cmd == "bootstrap":
        member = bootstrap(args.hf_user_id, args.login)
        print(f"bootstrapped owner: hf_user_id={member.hf_user_id} login={member.login}")
        return 0
    if args.cmd == "show":
        for m in snapshot().active_members():
            print(f"{m.role:12s}  {m.hf_user_id:8s}  {m.login}")
        return 0
    return 1


if __name__ == "__main__":
    import sys

    sys.exit(_main())
