"""Pending request schema: ``<bucket>/requests/pending.json``.

A signed-in user can request a reciter combination from the dashboard
modal. The submission transitions the row from ``CATALOGUED`` to
``AWAITING_ALIGNMENT`` ("Requested" pill) and parks the proposed catalog
edits + free-form comments in this sidecar file. Each entry is keyed by
delivery slug; at most one pending request per slug.

The audit log (``audit/<YYYY>-<MM>.jsonl``) is the authoritative record
for what happened — this sidecar is a denormalized index of "open
requests" for fast lookup by admin reviewers. If the file is missing or
corrupted, the data is recoverable by replaying the audit log.

Acceptance is implicit: when the alignment pipeline produces files under
``wip/<slug>/``, Inspector's auto-detect reconciler fires
``reciter.alignment_completed``, the proposed edits are applied to the
catalog, and the entry is cleared. Admins can also reject pre-acceptance
(soft = back to CATALOGUED, hard = discard).

Spec: docs/planning/inspector-deploy/v2/inspector-state-management.md
(request flow + admin rejection actions).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .audit import Actor
from .state import SLUG_RE


# Recording-year plausibility window: earliest plausible studio recording
# of Quranic recitation predates 1900 only theoretically; we accept 1900+.
# Upper bound is loose (current year + a small slack) so the schema doesn't
# break at year boundaries without redeploy.
MIN_RECORDING_YEAR = 1900
MAX_RECORDING_YEAR = 2100


class ProposedEdits(BaseModel):
    """User-submitted catalog edits, all optional.

    Only the fields the requester actually changed get populated. The
    server uses these to patch the catalog on auto-acceptance — fields
    left ``None`` mean "leave the existing catalog value alone."

    Riwayah and style are descriptive fields on the ``Delivery`` row, not
    parts of the slug — changing them does NOT re-key the row. Collisions
    with another delivery of the same reciter are non-blocking warnings.
    """

    model_config = ConfigDict(extra="forbid")

    riwayah: str | None = Field(default=None, min_length=1)
    style: str | None = Field(default=None, min_length=1)
    name_en: str | None = Field(default=None, min_length=1)
    name_ar: str | None = None
    country: str | None = Field(
        default=None,
        description="ISO-2 country code; validation deferred to catalog write",
    )
    recording_context: str | None = None
    recording_year: int | None = Field(
        default=None,
        ge=MIN_RECORDING_YEAR,
        le=MAX_RECORDING_YEAR,
    )

    def has_any(self) -> bool:
        """True iff at least one field is populated."""
        return any(
            v is not None
            for v in (
                self.riwayah,
                self.style,
                self.name_en,
                self.name_ar,
                self.country,
                self.recording_context,
                self.recording_year,
            )
        )


class PendingRequest(BaseModel):
    """One open user request for a delivery slug."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    submitted_at: datetime
    requester: Actor
    proposed_edits: ProposedEdits = Field(default_factory=ProposedEdits)
    comments: str | None = Field(default=None, max_length=1000)

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError(f"invalid slug: {v!r}")
        return v


class PendingRequestsFile(BaseModel):
    """Top-level schema for ``requests/pending.json``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    by_slug: dict[str, PendingRequest] = Field(default_factory=dict)
