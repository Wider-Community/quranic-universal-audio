"""Activity state schema — owner-only global tombstones for the public feed.

Holds ``deleted`` — audit_ids tombstoned by an owner so they're filtered out
of the public activity feed for everyone. The audit log itself is never
mutated; this list is the source of truth for "what should be hidden at
read time."

Per-user dismissals were dropped alongside the admin notifications rail
(see ``services/activity/activity_classification.py`` for the rationale —
admin awareness now lives in the Admin dashboard tabs, not a passive feed).
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
