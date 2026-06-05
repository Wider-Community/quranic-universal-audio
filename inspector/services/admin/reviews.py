"""Admin Reviews-tab read model (Flask-free).

Single whole-table JOIN over ``delivery_states`` + ``deliveries`` + ``reciters``
+ open ``claims``, filtered to the three states the Reviews tab covers
(``awaiting_review``, ``under_review``, ``released``).

The FE further splits ``under_review`` into "Marked ready" vs "Under review"
on ``open_claim.marked_ready_at``; ``released`` is the "Published" bucket. The
wire stays canonical.

No caching today — the row count is small (a few hundred), the query is one
JOIN, and the data refreshes after every admin action. If profiling shows we
need to amortize across concurrent maintainers, mirror the ``db_seq`` cache
pattern from ``services.admin.users``.
"""

from __future__ import annotations

from qua_shared.schemas import (
    AdminReviewClaimHistoryEntry,
    AdminReviewDetail,
    AdminReviewOpenClaim,
    AdminReviewRow,
    AdminReviewsResponse,
    AdminReviewTransition,
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
    ReciterState.RELEASED.value,
)


_SQL = (
    "SELECT "
    "  ds.slug, ds.state, ds.state_since, ds.last_job_finished_at, "
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
    with ``marked_ready_at`` set but neither a checklist NOR a bypass flag)
    or hasn't been marked at all. The list-row helper skips reading the
    submission; the drawer detail uses this directly.

    Bypass submissions store ``mark_ready_checklist = NULL`` +
    ``mark_ready_bypass_used = 1``; the returned object carries
    ``checklist=None`` + ``bypass_used=True`` so the admin Reviews drawer
    can render the bypass pill in lieu of the checklist list.
    """
    keys = row.keys()
    raw_checklist = row["mark_ready_checklist"] if "mark_ready_checklist" in keys else None
    bypass = bool(row["mark_ready_bypass_used"]) if "mark_ready_bypass_used" in keys else False

    if not raw_checklist and not bypass:
        return None

    checklist = _serde.json_loads(raw_checklist) if raw_checklist else None
    return MarkReadySubmission(
        checklist=checklist,
        comment_checks=row["mark_ready_comment_checks"] or "",
        comment_issues=row["mark_ready_comment_issues"] or "",
        bypass_used=bypass,
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

        # ``unread`` = the latest actionable event for this row is newer than
        # this admin's last view of the slug. Two signals share one viewed_at
        # cutoff: a marked-ready submission (under_review only) and a finished
        # timestamps job (``last_job_finished_at`` — success→released/Published,
        # failure→under_review/Marked-ready). ISO strings sort lexically. Mirrors
        # repo_review_views.count_unviewed_for_user so the per-row dot and the
        # polled aggregate agree.
        events: list[str] = []
        if r["state"] == ReciterState.UNDER_REVIEW.value and r["marked_ready_at"] is not None:
            events.append(r["marked_ready_at"])
        if r["last_job_finished_at"] is not None:
            events.append(r["last_job_finished_at"])
        unread = False
        if events:
            seen_at = viewed.get(r["slug"])
            unread = seen_at is None or seen_at < max(events)

        rows.append(
            AdminReviewRow(
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
            )
        )

    unviewed_count = sum(1 for row in rows if row.unread)
    return AdminReviewsResponse(
        rows=rows,
        unviewed_marked_ready=unviewed_count,
    ).model_dump(mode="json")


def unviewed_marked_ready_count(*, caller_hf_id: str) -> int:
    """Reviews rows the caller hasn't viewed — marked-ready submissions AND
    finished timestamps jobs (success→published / failure→marked-ready). Drives
    the entry-button dot poller. Cheap COUNT — never cached (per-caller +
    polled). (Name kept for call-site stability; semantics now cover both.)"""
    return repo_review_views.count_unviewed_for_user(caller_hf_id)


def mark_viewed(slug: str, *, caller_hf_id: str) -> bool:
    """Advance the caller's ``viewed_at`` for ``slug``. Returns False if the
    slug isn't in ``delivery_states`` (caller maps to 404). Durable write —
    same sync envelope the request-view path uses."""
    base = get_conn().execute("SELECT 1 FROM delivery_states WHERE slug = ?", (slug,)).fetchone()
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
        "  mark_ready_checklist, mark_ready_comment_checks, mark_ready_comment_issues, "
        "  mark_ready_bypass_used "
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
        "  mark_ready_checklist, mark_ready_comment_checks, mark_ready_comment_issues, "
        "  mark_ready_bypass_used "
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

    # Flagged-issue count from detailed.json (one cached read on drawer open).
    from services.segments.flags import count_flagged
    from services.storage.data_loader import load_detailed

    flagged_count = count_flagged(load_detailed(slug) or [])

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
        flagged_issues_count=flagged_count,
    ).model_dump(mode="json")
