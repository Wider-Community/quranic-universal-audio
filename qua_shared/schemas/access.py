"""Roles file schema: ``<bucket>/access/inspector_roles.json``.

Consolidated owners + maintainers. Inspector is sole writer; bootstrap via
hand-seed of the first owner. Soft-delete via ``removed_at`` so historical
membership stays queryable. ``hf_user_id`` is canonical (immutable); ``login``
is a refreshable display cache.

Spec: docs/planning/inspector-deploy/v2/inspector-state-management.md §9.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Role(str, Enum):
    CONTRIBUTOR = "contributor"  # default; not stored in the roles file
    MAINTAINER = "maintainer"
    OWNER = "owner"
    # Pipeline-internal principal — only ever stamped onto edit-history
    # batches written by the offline extraction pipeline
    # (`.local/extraction/segments/post_passes.py`). Never a real user
    # identity; never appears in the roles file. Inspector readers
    # display it as "pipeline" in History attribution; authorization
    # predicates never see it because the pipeline writes directly to
    # the bucket, not through the HTTP request path.
    PIPELINE = "pipeline"


# Roles that appear in the file. CONTRIBUTOR is the default for any authenticated
# user not present in the file; it is never written as a member row.
_STORED_ROLES = frozenset({Role.MAINTAINER, Role.OWNER})


class Member(BaseModel):
    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    hf_user_id: str = Field(..., min_length=1, description="OIDC sub; canonical key")
    login: str = Field(..., min_length=1, description="HF login; display cache")
    role: Role
    added_at: datetime
    added_by_hf_id: str = Field(..., min_length=1)
    removed_at: datetime | None = None
    removed_by_hf_id: str | None = None

    def is_active(self) -> bool:
        return self.removed_at is None


class RolesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    members: list[Member] = Field(default_factory=list)

    def active_members(self) -> list[Member]:
        return [m for m in self.members if m.is_active()]

    def find(self, hf_user_id: str) -> Member | None:
        """Return the active member with the given hf_user_id, if any."""
        for m in self.members:
            if m.hf_user_id == hf_user_id and m.is_active():
                return m
        return None

    def resolve_role(self, hf_user_id: str) -> Role:
        """Resolve effective role; non-members default to CONTRIBUTOR."""
        member = self.find(hf_user_id)
        return member.role if member is not None else Role.CONTRIBUTOR
