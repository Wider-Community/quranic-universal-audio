"""Capability resolver — the single authoritative authorization gate.

``can(user_or_actor, capability)`` is what every state handler, route, and
predicate calls. It answers "is this *tier* allowed this capability right now",
resolving the registry defaults (``qua_shared/schemas/capabilities.py``)
overlaid with any owner-set ``permission_overrides``. Ownership questions
("is this *your* claimed row") stay in ``permissions.py`` — a capability only
governs the tier / admin-override dimension layered on top of ownership.

Invariants enforced here (independent of the override table):
- **Owner is a superuser** — ``can(owner, anything) is True``.
- **manage_permissions is owner-only fixed** — never granted to a lower tier
  even if an override row is somehow forced in. This is the recovery anchor:
  only owners reach the Permissions tab, so the system can't be locked out.
- **Anonymous only where meaningful** — a non-``anon_eligible`` capability is
  always False for anonymous, regardless of any row.

Resolution is per-request and the matrix is cached on ``db_seq``; any committed
override write bumps ``db_seq`` and transparently invalidates the cache, so a
toggle takes effect on the very next request with no restart.
"""

from __future__ import annotations

from typing import Any

from qua_shared.schemas import CAPABILITIES, CAPABILITIES_BY_ID, TIERS
from qua_shared.schemas.capabilities import ANONYMOUS

from services.db import current_db_seq, repo_permissions
from services.storage import cache

from . import permissions


_OWNER = "owner"


def tier_of(user_or_actor: Any) -> str:
    """The matrix tier string for a caller. ``None`` → ``"anonymous"``.

    Returns the raw role value (``"contributor"`` / ``"maintainer"`` /
    ``"owner"``). A ``Role.PIPELINE`` principal (never reaches HTTP) would
    yield ``"pipeline"`` — not a matrix tier, so ``can`` denies every
    toggleable capability for it (safe default)."""
    if user_or_actor is None:
        return ANONYMOUS
    return permissions.role_of(user_or_actor).value


def resolve_grants() -> dict[tuple[str, str], bool]:
    """The full resolved grant matrix ``(capability_id, tier) -> allowed``.

    Registry defaults overlaid with ``permission_overrides``. ``owner`` is
    never a key (superuser); ``manage_permissions`` is never overridable;
    inapplicable cells (anonymous on a non-eligible cap, unknown tiers) are
    dropped. Cached on ``db_seq``."""
    seq = current_db_seq()
    cached = cache.get_capability_matrix_cache(seq)
    if cached is not None:
        return cached  # type: ignore[return-value]

    matrix: dict[tuple[str, str], bool] = {}
    for cap in CAPABILITIES:
        for tier in TIERS:
            if cap.applicable(tier):
                matrix[(cap.id, tier)] = cap.default_for(tier)

    for cap_id, tier, allowed in repo_permissions.all_overrides():
        cap = CAPABILITIES_BY_ID.get(cap_id)
        if cap is None or cap.owner_only_fixed or not cap.applicable(tier):
            continue  # stale id / fixed cap / inapplicable cell — ignore the row
        matrix[(cap_id, tier)] = allowed

    cache.set_capability_matrix_cache(seq, matrix)
    return matrix


def can(user_or_actor: Any, capability: str) -> bool:
    """Authoritative gate: does this caller currently have ``capability``?

    Raises ``ValueError`` for an unknown capability id — that's a programmer
    error (a typo in a gate), never a domain refusal."""
    cap = CAPABILITIES_BY_ID.get(capability)
    if cap is None:
        raise ValueError(f"unknown capability {capability!r}")

    tier = tier_of(user_or_actor)

    if cap.owner_only_fixed:
        return tier == _OWNER  # ignores the matrix entirely (recovery anchor)
    if tier == _OWNER:
        return True  # superuser
    if tier == ANONYMOUS and not cap.anon_eligible:
        return False
    return resolve_grants().get((cap.id, tier), False)


def capabilities_for(user_or_actor: Any) -> list[str]:
    """Every capability id the caller currently holds — for ``/api/me`` so the
    FE can gate UI immediately. Order follows the registry (stable)."""
    return [c.id for c in CAPABILITIES if can(user_or_actor, c.id)]
