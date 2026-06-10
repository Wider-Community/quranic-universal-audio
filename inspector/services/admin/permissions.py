"""Admin Permissions-tab service: build the capability matrix + apply toggles.

Read side (``build_matrix``) projects the registry
(``qua_shared/schemas/capabilities.py``) overlaid with the live
``permission_overrides`` into the grouped wire shape the FE renders. Write side
(``set_grant`` / ``reset_grant``) persists one override cell inside a durable
transaction paired with an ``access.permission_changed`` audit row, so the
change is durable + auditable and (via the db_seq bump) takes effect on the
next request.

Owner-only fixed capabilities (``manage_permissions``) and inapplicable cells
(anonymous on an action cap) are refused here as well as in the resolver —
defense in depth.
"""

from __future__ import annotations

from qua_shared.schemas import (
    CAPABILITIES,
    CAPABILITIES_BY_ID,
    GROUP_ORDER,
    TIERS,
    AdminCapabilityRow,
    AdminCapabilityTierState,
    AdminPermissionGroup,
    AdminPermissionsResponse,
)
from qua_shared.schemas.config.capabilities import ANONYMOUS
from services.auth import capabilities as _resolver
from services.db import repo_access, repo_permissions
from services.db import sync as _sync
from services.state import audit


class PermissionChangeError(Exception):
    """Invalid toggle request (unknown cap/tier, fixed cap, inapplicable tier).
    The route maps it to a 400."""


# ---- Read ----


def build_matrix() -> AdminPermissionsResponse:
    """The full grouped capability matrix (registry ⊕ overrides)."""
    grants = _resolver.resolve_grants()
    override_keys = {(c, t) for (c, t, _) in repo_permissions.all_overrides()}

    groups: list[AdminPermissionGroup] = []
    for group_name in GROUP_ORDER:
        rows: list[AdminCapabilityRow] = []
        for cap in CAPABILITIES:
            if cap.group != group_name:
                continue
            cells: dict[str, AdminCapabilityTierState] = {}
            for tier in TIERS:
                if cap.applicable(tier):
                    cells[tier] = AdminCapabilityTierState(
                        allowed=grants.get((cap.id, tier), cap.default_for(tier)),
                        applicable=True,
                        is_default=(cap.id, tier) not in override_keys,
                    )
                else:
                    cells[tier] = AdminCapabilityTierState(
                        allowed=None,
                        applicable=False,
                        is_default=True,
                    )
            rows.append(
                AdminCapabilityRow(
                    id=cap.id,
                    label=cap.label,
                    description=cap.description,
                    anon_eligible=cap.anon_eligible,
                    owner_only_fixed=cap.owner_only_fixed,
                    anonymous=cells[TIERS[0]],
                    contributor=cells[TIERS[1]],
                    maintainer=cells[TIERS[2]],
                )
            )
        groups.append(AdminPermissionGroup(group=group_name, capabilities=rows))
    return AdminPermissionsResponse(groups=groups, tiers=list(TIERS))


# ---- Write ----


def _validate(capability_id: str, tier: str):
    cap = CAPABILITIES_BY_ID.get(capability_id)
    if cap is None:
        raise PermissionChangeError(f"unknown capability {capability_id!r}")
    if cap.owner_only_fixed:
        raise PermissionChangeError(f"{capability_id!r} is owner-only and cannot be changed")
    if tier not in TIERS:
        raise PermissionChangeError(f"unknown tier {tier!r}")
    if tier == ANONYMOUS and not cap.anon_eligible:
        raise PermissionChangeError(f"{capability_id!r} is not applicable to anonymous users")
    return cap


def set_grant(*, capability_id: str, tier: str, allowed: bool, actor) -> bool:
    """Persist one override cell + audit. Returns the new effective value."""
    cap = _validate(capability_id, tier)
    with _sync.durable_transaction():
        repo_access.ensure_user(actor.hf_user_id, login=actor.login_at_time)
        prev = repo_permissions.get_override(capability_id, tier)
        before = prev if prev is not None else cap.default_for(tier)
        repo_permissions.set_override(
            capability_id=capability_id,
            tier=tier,
            allowed=allowed,
            set_by=actor.hf_user_id,
        )
        audit.append(
            event="access.permission_changed",
            actor=actor,
            payload={
                "capability": capability_id,
                "tier": tier,
                "before": before,
                "after": allowed,
                "reset": False,
            },
        )
    return allowed


def reset_grant(*, capability_id: str, tier: str, actor) -> bool:
    """Clear an override cell (back to the registry default) + audit. Returns
    the default value now in effect."""
    cap = _validate(capability_id, tier)
    after = cap.default_for(tier)
    with _sync.durable_transaction():
        repo_access.ensure_user(actor.hf_user_id, login=actor.login_at_time)
        prev = repo_permissions.get_override(capability_id, tier)
        before = prev if prev is not None else after
        repo_permissions.clear_override(capability_id=capability_id, tier=tier)
        audit.append(
            event="access.permission_changed",
            actor=actor,
            payload={
                "capability": capability_id,
                "tier": tier,
                "before": before,
                "after": after,
                "reset": True,
            },
        )
    return after
