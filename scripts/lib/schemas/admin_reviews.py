"""Admin Reviews-tab wire schemas.

Backed by ``/api/admin/reviews/list`` (maintainer+). Per-recitation rows
across the four buckets the Reviews tab covers (Marked ready, Under review,
Published, Available for review). The state-vs-bucket mapping is computed
on the FE — the wire only carries the canonical state + open-claim shape:

* Marked ready = ``state == "under_review"`` AND ``open_claim.marked_ready_at`` set
* Under review = ``state == "under_review"`` AND ``open_claim.marked_ready_at`` null
* Published    = ``state IN ("awaiting_timestamps", "released")``
* Available    = ``state == "awaiting_review"``

Timestamps are ISO-8601 UTC strings exactly as stored in the substrate; the
FE formats relatives. ``ConfigDict(extra="allow")`` for forward compatibility
per the schema convention.

FE-facing: re-exported from ``fe_types.py`` and code-generated into
``inspector/frontend/src/lib/types/generated/schemas.ts`` via
``inspector/scripts/regen_fe_types.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AdminReviewOpenClaim(BaseModel):
    model_config = ConfigDict(extra="allow")

    assignee_id: str
    login: str | None = None
    claimed_at: str | None = None
    marked_ready_at: str | None = None


class AdminReviewRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    slug: str
    state: str
    state_since: str | None = None
    reciter_id: str
    name_ar: str | None = None
    name_en: str | None = None
    riwayah: str
    style: str
    channel: str
    open_claim: AdminReviewOpenClaim | None = None


class AdminReviewsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    rows: list[AdminReviewRow] = Field(default_factory=list)
