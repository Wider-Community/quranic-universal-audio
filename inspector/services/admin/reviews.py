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
    AdminReviewOpenClaim,
    AdminReviewRow,
    AdminReviewsResponse,
    ReciterState,
)

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
