"""Admin Reviews-tab wire schemas.

Backed by ``/api/admin/reviews/list`` (maintainer+). Per-recitation rows for
the slimmed Reviews tab, which covers read-only oversight of two buckets
(Under review + Available for review). The state-vs-bucket mapping is computed
on the FE — the wire only carries the canonical state + open-claim shape:

* Under review = ``state == "under_review"`` AND ``open_claim.marked_ready_at`` null
* Available    = ``state == "awaiting_review"``

Marked-ready and released recitations moved to the Releases tab.

Timestamps are ISO-8601 UTC strings exactly as stored in the substrate; the
FE formats relatives. ``ConfigDict(extra="allow")`` for forward compatibility
per the schema convention.

FE-facing: re-exported from ``fe_types.py`` and code-generated into
``inspector/frontend/src/lib/types/generated/schemas.ts`` via
``scripts/codegen/regen_fe_types.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .mark_ready import MarkReadySubmission


class AdminReviewOpenClaim(BaseModel):
    model_config = ConfigDict(extra="allow")

    assignee_id: str
    login: str | None = None
    claimed_at: str | None = None
    marked_ready_at: str | None = None
    # Populated only once the reviewer submits a mark-ready form. Null on
    # rows that are claimed-but-not-marked. Cleared together with
    # ``marked_ready_at`` on unmark / release / reassign.
    mark_ready_submission: MarkReadySubmission | None = None


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


# ---- detail drawer ----


class AdminReviewClaimHistoryEntry(BaseModel):
    """One claim row (open or closed) for the reviewer-history table.

    A closed claim that had a mark-ready submission keeps the submission
    on the row — admins can audit past cycles' attestations even after a
    send-back-and-re-mark.
    """

    model_config = ConfigDict(extra="allow")

    assignee_id: str
    login: str | None = None
    claimed_at: str | None = None
    released_at: str | None = None
    marked_ready_at: str | None = None
    close_reason: str | None = None
    mark_ready_submission: MarkReadySubmission | None = None


class AdminReviewTransition(BaseModel):
    """One row from the ``transitions`` table, slim-shaped for the timeline."""

    model_config = ConfigDict(extra="allow")

    ts: str
    event: str
    from_state: str | None = None
    to_state: str | None = None
    actor_login: str | None = None
    actor_role: str | None = None
    reason: str | None = None


class AdminReviewDetail(BaseModel):
    """Full per-recitation payload for the General drawer.

    ``flagged_issues_count`` is the number of segments carrying a manual flag
    (``detailed.json`` segs with a ``flag`` block). Computed from one cached
    ``load_detailed`` read on drawer open; the FE hides the pill when it is 0.
    """

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
    current_claim: AdminReviewOpenClaim | None = None
    claim_history: list[AdminReviewClaimHistoryEntry] = Field(default_factory=list)
    transitions: list[AdminReviewTransition] = Field(default_factory=list)
    timestamps_job_ids: list[str] = Field(default_factory=list)
    flagged_issues_count: int = 0
