"""Admin Reviews-tab read model (Flask-free).

Single whole-table JOIN over ``delivery_states`` + ``deliveries`` + ``reciters``
+ open ``claims``, filtered to the four states the Reviews tab covers
(``awaiting_review``, ``under_review``, ``awaiting_timestamps``, ``released``).

The FE further splits ``under_review`` into "Marked ready" vs "Under review"
on ``open_claim.marked_ready_at`` and collapses ``awaiting_timestamps``+
``released`` into one "Published" bucket; the wire stays canonical.

No caching today — the row count is small (a few hundred), the query is one
JOIN, and the data refreshes after every admin action. If profiling shows we
need to amortize across concurrent maintainers, mirror the ``db_seq`` cache
pattern from ``services.admin.users``.
"""

from __future__ import annotations

from scripts.lib.schemas import (
    AdminReviewClaimHistoryEntry,
    AdminReviewDetail,
    AdminReviewOpenClaim,
    AdminReviewRow,
    AdminReviewTransition,
    AdminReviewValidation,
    AdminReviewsResponse,
    ReciterState,
)

from services.db import _serde
from services.db.connection import get_conn


# States the Reviews tab covers.
_BUCKET_STATES: tuple[str, ...] = (
    ReciterState.AWAITING_REVIEW.value,
    ReciterState.UNDER_REVIEW.value,
    ReciterState.AWAITING_TIMESTAMPS.value,
    ReciterState.RELEASED.value,
)


_SQL = (
    "SELECT "
    "  ds.slug, ds.state, ds.state_since, "
    "  d.reciter_id, d.riwayah, d.style, d.channel, "
    "  r.name_ar, r.name_en, "
    "  c.assignee_id, c.assignee_login_snapshot, c.claimed_at, c.marked_ready_at "
    "FROM delivery_states ds "
    "JOIN deliveries d ON d.slug = ds.slug "
    "JOIN reciters r ON r.reciter_id = d.reciter_id "
    "LEFT JOIN claims c ON c.slug = ds.slug AND c.released_at IS NULL "
    f"WHERE ds.state IN ({','.join(['?'] * len(_BUCKET_STATES))}) "
    "ORDER BY ds.slug"
)


def list_reviews() -> dict:
    """Assembled Reviews-tab payload (``AdminReviewsResponse`` dump)."""
    rows: list[AdminReviewRow] = []
    for r in get_conn().execute(_SQL, _BUCKET_STATES).fetchall():
        open_claim: AdminReviewOpenClaim | None = None
        if r["assignee_id"] is not None:
            open_claim = AdminReviewOpenClaim(
                assignee_id=r["assignee_id"],
                login=r["assignee_login_snapshot"],
                claimed_at=r["claimed_at"],
                marked_ready_at=r["marked_ready_at"],
            )
        rows.append(AdminReviewRow(
            slug=r["slug"],
            state=r["state"],
            state_since=r["state_since"],
            reciter_id=r["reciter_id"],
            name_ar=r["name_ar"],
            name_en=r["name_en"],
            riwayah=r["riwayah"],
            style=r["style"],
            channel=r["channel"],
            open_claim=open_claim,
        ))
    return AdminReviewsResponse(rows=rows).model_dump(mode="json")


# ---- detail drawer ----


def get_review_detail(slug: str) -> dict | None:
    """Per-slug payload for the General drawer.

    Returns ``None`` when the slug isn't in ``delivery_states`` (caller maps
    to 404). Three small bounded queries: base + open claim + closed claims +
    transitions. Cheap relative to ``validate_reciter_segments`` so it's safe
    to fetch eagerly on every drawer open.
    """
    conn = get_conn()

    base = conn.execute(
        "SELECT ds.slug, ds.state, ds.state_since, ds.timestamps_job_ids, "
        "  d.reciter_id, d.riwayah, d.style, d.channel, "
        "  r.name_ar, r.name_en "
        "FROM delivery_states ds "
        "JOIN deliveries d ON d.slug = ds.slug "
        "JOIN reciters r ON r.reciter_id = d.reciter_id "
        "WHERE ds.slug = ?",
        (slug,),
    ).fetchone()
    if base is None:
        return None

    current_row = conn.execute(
        "SELECT assignee_id, assignee_login_snapshot, claimed_at, marked_ready_at "
        "FROM claims WHERE slug = ? AND released_at IS NULL",
        (slug,),
    ).fetchone()
    current_claim: AdminReviewOpenClaim | None = None
    if current_row is not None:
        current_claim = AdminReviewOpenClaim(
            assignee_id=current_row["assignee_id"],
            login=current_row["assignee_login_snapshot"],
            claimed_at=current_row["claimed_at"],
            marked_ready_at=current_row["marked_ready_at"],
        )

    history_rows = conn.execute(
        "SELECT assignee_id, assignee_login_snapshot, claimed_at, released_at, "
        "  marked_ready_at, close_reason "
        "FROM claims WHERE slug = ? "
        "ORDER BY claimed_at DESC",
        (slug,),
    ).fetchall()
    claim_history = [
        AdminReviewClaimHistoryEntry(
            assignee_id=r["assignee_id"],
            login=r["assignee_login_snapshot"],
            claimed_at=r["claimed_at"],
            released_at=r["released_at"],
            marked_ready_at=r["marked_ready_at"],
            close_reason=r["close_reason"],
        )
        for r in history_rows
    ]

    transition_rows = conn.execute(
        "SELECT ts, event, from_state, to_state, actor_login_snapshot, "
        "  actor_role_snapshot, reason "
        "FROM transitions WHERE slug = ? "
        "ORDER BY seq DESC",
        (slug,),
    ).fetchall()
    transitions = [
        AdminReviewTransition(
            ts=r["ts"],
            event=r["event"],
            from_state=r["from_state"],
            to_state=r["to_state"],
            actor_login=r["actor_login_snapshot"],
            actor_role=r["actor_role_snapshot"],
            reason=r["reason"],
        )
        for r in transition_rows
    ]

    job_ids = _serde.json_loads(base["timestamps_job_ids"]) or []

    return AdminReviewDetail(
        slug=base["slug"],
        state=base["state"],
        state_since=base["state_since"],
        reciter_id=base["reciter_id"],
        name_ar=base["name_ar"],
        name_en=base["name_en"],
        riwayah=base["riwayah"],
        style=base["style"],
        channel=base["channel"],
        current_claim=current_claim,
        claim_history=claim_history,
        transitions=transitions,
        timestamps_job_ids=job_ids,
    ).model_dump(mode="json")


def get_review_validation(slug: str) -> dict:
    """Validation category counts for a slug.

    Wraps the existing ``validate_reciter_segments`` and returns just the
    accordion-shaped counts. ``has_data=False`` when the reciter has no
    ``detailed.json`` on the bucket yet (fresh ``awaiting_review`` rows).
    """
    # Local import — the validation module pulls heavy bucket loaders at
    # import time; keep the top-level module light for the list endpoint.
    from services.validation import validate_reciter_segments

    result = validate_reciter_segments(slug)
    if result is None:
        return AdminReviewValidation(slug=slug, has_data=False).model_dump(mode="json")
    return AdminReviewValidation(
        slug=slug,
        category_counts=result.get("category_counts") or {},
        has_data=True,
    ).model_dump(mode="json")
