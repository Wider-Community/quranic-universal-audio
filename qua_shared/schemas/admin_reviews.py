"""Admin Reviews-tab wire schemas.

Backed by ``/api/admin/reviews/list`` (maintainer+). Per-recitation rows
across the four buckets the Reviews tab covers (Marked ready, Under review,
Published, Available for review). The state-vs-bucket mapping is computed
on the FE — the wire only carries the canonical state + open-claim shape:

* Marked ready = ``state == "under_review"`` AND ``open_claim.marked_ready_at`` set
* Under review = ``state == "under_review"`` AND ``open_claim.marked_ready_at`` null
* Published    = ``state == "released"``
* Available    = ``state == "awaiting_review"``

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
    # True only for ``state == under_review`` AND open_claim has a
    # ``marked_ready_at`` later than this caller's recorded ``review_views``
    # row (or no row exists). Drives the per-row ``.unread`` dot in the FE.
    # Defaults to False so non-marked-ready rows stay clean even if a stale
    # view row would otherwise satisfy the predicate vacuously.
    unread: bool = False


class AdminReviewsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    rows: list[AdminReviewRow] = Field(default_factory=list)
    # Per-caller count of marked-ready entries this admin hasn't viewed yet.
    # Mirrors ``AdminRequestsResponse.unviewed_count`` so the compartment can
    # sync the dashboard store on every fetch without a second roundtrip.
    unviewed_marked_ready: int = 0


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

    Carries everything except the live validation counts (lazy-loaded via
    ``/api/admin/reviews/<slug>/validation`` only when the accordion expands —
    ``validate_reciter_segments`` walks the bucket and is too expensive to
    eager-fetch on every drawer open).
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


class AdminReviewValidation(BaseModel):
    """Validation category counts for one slug.

    ``has_data`` is False when ``validate_reciter_segments`` returns None
    (no ``detailed.json`` on the bucket yet — typical for fresh
    ``awaiting_review`` rows that haven't been touched).
    """

    model_config = ConfigDict(extra="allow")

    slug: str
    category_counts: dict[str, int] = Field(default_factory=dict)
    has_data: bool = False
