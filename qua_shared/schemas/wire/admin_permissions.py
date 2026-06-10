"""Admin-dashboard Permissions-tab wire schemas.

Read model served by ``GET /api/admin/permissions`` (owner-only). The backend
transforms the capability registry (``qua_shared/schemas/capabilities.py``)
overlaid with the live ``permission_overrides`` into this grouped matrix. Each
tier cell carries:

- ``allowed``   — the *effective* grant (default overlaid with override);
  ``null`` when the cell is not applicable (e.g. anonymous on an action cap).
- ``applicable``— whether this tier is a meaningful column for the capability
  (False ⇒ render N/A).
- ``is_default``— True when no override row exists (cell sits at the baseline).

``owner`` is never a cell here — owners are superusers. ``ConfigDict(
extra="allow")`` per the schema convention.

FE-facing: re-exported from ``fe_types.py`` and code-generated into
``inspector/frontend/src/lib/types/generated/schemas.ts`` via
``scripts/codegen/regen_fe_types.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AdminCapabilityTierState(BaseModel):
    model_config = ConfigDict(extra="allow")

    allowed: bool | None = None
    applicable: bool = True
    is_default: bool = True


class AdminCapabilityRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    label: str
    description: str
    anon_eligible: bool = False
    owner_only_fixed: bool = False
    anonymous: AdminCapabilityTierState = Field(default_factory=AdminCapabilityTierState)
    contributor: AdminCapabilityTierState = Field(default_factory=AdminCapabilityTierState)
    maintainer: AdminCapabilityTierState = Field(default_factory=AdminCapabilityTierState)


class AdminPermissionGroup(BaseModel):
    model_config = ConfigDict(extra="allow")

    group: str
    capabilities: list[AdminCapabilityRow] = Field(default_factory=list)


class AdminPermissionsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    groups: list[AdminPermissionGroup] = Field(default_factory=list)
    tiers: list[str] = Field(default_factory=list)
