"""Activity state schema: ``<bucket>/activity/state.json``.

Out-of-band sidecar to the append-only audit log. Holds two things:

- ``deleted`` — global tombstones. Audit records whose ``audit_id`` appears
  here are filtered out of the public activity feed for everyone.
- ``dismissals`` — per-user dismissals. Maps ``hf_user_id`` to a list of
  audit_ids the user has dismissed from the admin activity rail.

The audit log itself is never mutated; this file is the source of truth for
"what should be hidden at read time". Owners can permanently delete from the
public feed; maintainers and owners can dismiss-for-themselves on the admin
feed.

Spec: docs/planning/inspector-deploy/v2/inspector-state-management.md (admin
activity controls).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ActivityState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    deleted: list[str] = Field(
        default_factory=list,
        description="Global tombstones — audit_ids hidden from the public feed.",
    )
    dismissals: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Per-user dismissals: hf_user_id -> [audit_ids].",
    )
