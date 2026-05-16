"""Roles file service: ``<bucket>/access/inspector_roles.json``.

In-memory cache hydrated at startup, replaced atomically on each write
(Inspector is sole writer, so the cache is correct by construction —
there's no external authority to refresh from).

Bootstrap: a one-shot hand-seed at Phase 0 inserts the first owner.
Thereafter all mutations go through ``grant()`` / ``revoke()`` / ``update()``.

Spec: docs/planning/inspector-deploy/v2/inspector-state-management.md §9.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from scripts.lib.schemas import Actor, Member, Role, RolesFile

from . import permissions
from services.state import audit
from services.storage import storage_paths
from services.storage.hf_bucket import StorageNotFound, get_backend

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


# ---- In-memory store ----


_store: RolesFile = RolesFile()
_store_lock = threading.Lock()


def hydrate() -> None:
    """Load (or initialize) the roles file from the bucket. Idempotent."""
    global _store
    backend = get_backend()
    try:
        raw = backend.read_json(storage_paths.roles_path())
        loaded = RolesFile.model_validate(raw)
    except StorageNotFound:
        logger.warning(
            "access: roles file missing on bucket; initializing empty in-memory "
            "store. Bootstrap an owner via inspector.services.access bootstrap."
        )
        loaded = RolesFile()
    with _store_lock:
        _store = loaded


def snapshot() -> RolesFile:
    """Return a copy of the current roles file."""
    with _store_lock:
        return _store.model_copy(deep=True)


def resolve_role(hf_user_id: str) -> Role:
    """Return effective role for ``hf_user_id``. Non-members → CONTRIBUTOR."""
    with _store_lock:
        return _store.resolve_role(hf_user_id)


def find_member(hf_user_id: str) -> Member | None:
    with _store_lock:
        return _store.find(hf_user_id)


# ---- Mutations ----


def _persist(new_store: RolesFile) -> None:
    backend = get_backend()
    backend.write_json_atomic(
        storage_paths.roles_path(),
        new_store.model_dump(mode="json"),
    )


def _require_role(actor: Actor, *allowed: Role) -> None:
    if not permissions.has_role(actor, *allowed):
        raise NotAuthorized(
            f"actor role {actor.role!r} cannot perform this action; "
            f"requires {[r.value for r in allowed]}"
        )


def grant(
    *,
    hf_user_id: str,
    login: str,
    role: Role,
    actor: Actor,
    reason: str | None = None,
) -> Member:
    """Add a new member or re-activate a soft-deleted one.

    Authorization:
    - Granting ``OWNER`` requires actor role == OWNER.
    - Granting ``MAINTAINER`` requires actor role >= MAINTAINER.
    """
    global _store
    if role == Role.CONTRIBUTOR:
        raise AccessError("CONTRIBUTOR is implicit; do not grant it explicitly")

    if role == Role.OWNER:
        _require_role(actor, Role.OWNER)
    else:
        _require_role(actor, Role.MAINTAINER, Role.OWNER)

    with _store_lock:
        existing = _store.find(hf_user_id)
        if existing is not None:
            raise MemberAlreadyActive(
                f"member {hf_user_id} already active with role {existing.role}"
            )
        new_member = Member(
            hf_user_id=hf_user_id,
            login=login,
            role=role,
            added_at=datetime.now(timezone.utc),
            added_by_hf_id=actor.hf_user_id,
        )
        new_store = _store.model_copy(deep=True)
        new_store.members.append(new_member)
        _persist(new_store)
        _store = new_store

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
    return new_member


def revoke(
    *,
    hf_user_id: str,
    actor: Actor,
    reason: str | None = None,
) -> Member:
    """Soft-delete a member by setting ``removed_at``."""
    global _store
    _require_role(actor, Role.MAINTAINER, Role.OWNER)

    with _store_lock:
        target = _store.find(hf_user_id)
        if target is None:
            raise MemberNotFound(hf_user_id)
        # Maintainers cannot revoke owners.
        if permissions.is_owner(target) and not permissions.is_owner(actor):
            raise NotAuthorized("only OWNER can revoke an OWNER member")

        now = datetime.now(timezone.utc)
        new_store = _store.model_copy(deep=True)
        for m in new_store.members:
            if m.hf_user_id == hf_user_id and m.is_active():
                m.removed_at = now
                m.removed_by_hf_id = actor.hf_user_id
                target = m
                break
        _persist(new_store)
        _store = new_store

    audit.append(
        event="access.role_revoked",
        actor=actor,
        payload={
            "target_hf_user_id": hf_user_id,
            "target_login": target.login,
            "role": target.role,
        },
        reason=reason,
    )
    return target


def update(
    *,
    hf_user_id: str,
    actor: Actor,
    login: str | None = None,
    role: Role | None = None,
    reason: str | None = None,
) -> Member:
    """Refresh login cache or change role tier on an active member."""
    global _store
    _require_role(actor, Role.MAINTAINER, Role.OWNER)
    if role == Role.OWNER:
        _require_role(actor, Role.OWNER)

    with _store_lock:
        target = _store.find(hf_user_id)
        if target is None:
            raise MemberNotFound(hf_user_id)
        if permissions.is_owner(target) and not permissions.is_owner(actor):
            raise NotAuthorized("only OWNER can edit an OWNER member")

        new_store = _store.model_copy(deep=True)
        patch: dict = {}
        for m in new_store.members:
            if m.hf_user_id == hf_user_id and m.is_active():
                if login is not None and login != m.login:
                    patch["login"] = {"from": m.login, "to": login}
                    m.login = login
                if role is not None and Role(m.role) != role:
                    patch["role"] = {"from": m.role, "to": role.value}
                    m.role = role
                target = m
                break
        _persist(new_store)
        _store = new_store

    audit.append(
        event="access.role_updated",
        actor=actor,
        payload={"target_hf_user_id": hf_user_id, "patch": patch},
        reason=reason,
    )
    return target


# ---- Bootstrap (one-shot CLI) ----


def bootstrap(hf_user_id: str, login: str) -> Member:
    """Seed the first OWNER into an empty roles file. Idempotent only on
    empty state — if any active member exists this raises.

    Intended for ``python -m inspector.services.access bootstrap --hf-user-id
    ... --login ...``.
    """
    global _store
    hydrate()
    if _store.active_members():
        raise AccessError(
            "bootstrap refused: roles file already has active members. "
            "Use grant() with an authenticated owner instead."
        )
    new_member = Member(
        hf_user_id=hf_user_id,
        login=login,
        role=Role.OWNER,
        added_at=datetime.now(timezone.utc),
        added_by_hf_id="bootstrap",
    )
    new_store = RolesFile(members=[new_member])
    _persist(new_store)
    with _store_lock:
        _store = new_store

    # Audit with a synthetic bootstrap actor (we don't have a real actor yet).
    audit.append(
        event="access.role_granted",
        actor=Actor(
            hf_user_id="bootstrap",
            login_at_time="bootstrap",
            role=Role.OWNER,
        ),
        payload={
            "target_hf_user_id": hf_user_id,
            "target_login": login,
            "role": Role.OWNER.value,
        },
        reason="phase-1 bootstrap",
    )
    return new_member


# ---- CLI entry point ----


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="inspector.services.access")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    boot = subparsers.add_parser("bootstrap", help="Seed the first OWNER")
    boot.add_argument("--hf-user-id", required=True)
    boot.add_argument("--login", required=True)

    show = subparsers.add_parser("show", help="Print active members")

    args = parser.parse_args(argv)
    if args.cmd == "bootstrap":
        member = bootstrap(args.hf_user_id, args.login)
        print(f"bootstrapped owner: hf_user_id={member.hf_user_id} login={member.login}")
        return 0
    if args.cmd == "show":
        hydrate()
        for m in snapshot().active_members():
            print(f"{m.role:12s}  {m.hf_user_id:8s}  {m.login}")
        return 0
    return 1


if __name__ == "__main__":
    import sys

    sys.exit(_main())
