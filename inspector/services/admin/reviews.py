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
    MarkReadySubmission,
    ReciterState,
)

from services.db import _serde, repo_review_views
from services.db import sync as _sync
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


def _build_submission(row) -> MarkReadySubmission | None:
    """Assemble a ``MarkReadySubmission`` from a claims row, or None.

    Returns None when the row pre-dates the mark-ready form (legacy claims
    with ``marked_ready_at`` set but no checklist JSON) or hasn't been
    marked at all. The list-row helper skips reading the submission; the
    drawer detail uses this directly.
    """
    raw = row["mark_ready_checklist"] if "mark_ready_checklist" in row.keys() else None
    if not raw:
        return None
    checklist = _serde.json_loads(raw)
    if not checklist:
        return None
    return MarkReadySubmission(
        checklist=checklist,
        comment_checks=row["mark_ready_comment_checks"] or "",
        comment_issues=row["mark_ready_comment_issues"] or "",
    )


def list_reviews(*, caller_hf_id: str) -> dict:
    """Assembled Reviews-tab payload (``AdminReviewsResponse`` dump).

    Per-caller: each row carries an ``unread`` boolean (true only for
    marked-ready entries whose ``marked_ready_at`` is later than this
    admin's recorded view), and the response carries an aggregate
    ``unviewed_marked_ready`` count used by the entry-button dot / tab pill.
    """
    viewed = repo_review_views.viewed_at_for_user(caller_hf_id)

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

        # ``unread`` is strict: only marked-ready rows ever qualify, so the
        # FE can render the dot from this flag alone without re-deriving
        # the bucket predicate. Non-marked-ready rows default to False.
        unread = False
        if (
            r["state"] == ReciterState.UNDER_REVIEW.value
            and open_claim is not None
            and open_claim.marked_ready_at is not None
        ):
            seen_at = viewed.get(r["slug"])
            unread = seen_at is None or seen_at < open_claim.marked_ready_at

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
            unread=unread,
        ))

    unviewed_count = sum(1 for row in rows if row.unread)
    return AdminReviewsResponse(
        rows=rows,
        unviewed_marked_ready=unviewed_count,
    ).model_dump(mode="json")


def unviewed_marked_ready_count(*, caller_hf_id: str) -> int:
    """Marked-ready rows the caller hasn't viewed. Drives the entry-button
    dot poller. Cheap COUNT — never cached (per-caller + polled)."""
    return repo_review_views.count_unviewed_marked_ready_for_user(caller_hf_id)


def mark_viewed(slug: str, *, caller_hf_id: str) -> bool:
    """Advance the caller's ``viewed_at`` for ``slug``. Returns False if the
    slug isn't in ``delivery_states`` (caller maps to 404). Durable write —
    same sync envelope the request-view path uses."""
    base = get_conn().execute(
        "SELECT 1 FROM delivery_states WHERE slug = ?", (slug,)
    ).fetchone()
    if base is None:
        return False
    with _sync.durable_transaction():
        repo_review_views.mark_viewed(slug, caller_hf_id)
    return True


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
        "SELECT assignee_id, assignee_login_snapshot, claimed_at, marked_ready_at, "
        "  mark_ready_checklist, mark_ready_comment_checks, mark_ready_comment_issues "
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
            mark_ready_submission=_build_submission(current_row),
        )

    history_rows = conn.execute(
        "SELECT assignee_id, assignee_login_snapshot, claimed_at, released_at, "
        "  marked_ready_at, close_reason, "
        "  mark_ready_checklist, mark_ready_comment_checks, mark_ready_comment_issues "
        "FROM claims WHERE slug = ? AND released_at IS NOT NULL "
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
            mark_ready_submission=_build_submission(r),
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
