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
    # ``extra="ignore"`` so a legacy ``activity/state.json`` carrying the
    # retired per-user ``dismissals`` map still validates cleanly when the
    # one-shot JSON-to-SQLite migrator reads it — the field is dropped at
    # load time, modern code only sees ``deleted``. New code should never
    # produce unknown keys.
    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    deleted: list[str] = Field(
        default_factory=list,
        description="Global tombstones — audit_ids hidden from the public feed.",
    )
