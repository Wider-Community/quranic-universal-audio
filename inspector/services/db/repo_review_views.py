"""Per-admin view marks for the Reviews tab → marked-ready notification dot.

Mirrors ``repo_requests`` view marks but keyed by slug (not request id) and
**upserts** the timestamp on every write so the latest view always wins.
The comparison against ``claims.marked_ready_at`` is what makes the unread
predicate cycle-safe — see migration 0005's header for the full story.
"""

from __future__ import annotations

from datetime import datetime

from . import _serde
from .connection import get_conn
from . import repo_access


def mark_viewed(slug: str, hf_user_id: str, *, at: datetime | None = None) -> None:
    """Record (or advance) the calling admin's viewed_at for ``slug``.

    Upsert semantics: a later open of the same slug overwrites the prior
    viewed_at, so a re-marked-ready row that the admin re-views moves the
    unread cutoff forward. ``ensure_user`` keeps the FK valid for callers
    whose ``users`` row hasn't been created yet (mirrors repo_requests).
    """
    repo_access.ensure_user(hf_user_id)
    get_conn().execute(
        "INSERT INTO review_views(slug, hf_user_id, viewed_at) "
        "VALUES (?,?,?) "
        "ON CONFLICT(slug, hf_user_id) DO UPDATE SET viewed_at = excluded.viewed_at",
        (slug, hf_user_id, _serde.to_iso(at or _serde.now())),
    )


def viewed_at_for_user(hf_user_id: str) -> dict[str, str]:
    """``{slug: viewed_at_iso}`` for every slug this admin has ever viewed.

    The Reviews-tab list endpoint calls this once per request and joins
    in-memory against the assembled rows — cheaper than per-row LEFT JOIN
    on a query already touching three tables.
    """
    rows = get_conn().execute(
        "SELECT slug, viewed_at FROM review_views WHERE hf_user_id = ?",
        (hf_user_id,),
    ).fetchall()
    return {r["slug"]: r["viewed_at"] for r in rows}


def count_unviewed_marked_ready_for_user(hf_user_id: str) -> int:
    """Marked-ready entries this admin hasn't viewed since the latest mark.

    Single COUNT over open claims with a non-null ``marked_ready_at``,
    joined against ``delivery_states`` (the slug must still be under review —
    skips claims orphaned by a manual force-set on a parallel surface), with
    a NOT-EXISTS / less-than predicate on ``review_views``.
    """
    return int(get_conn().execute(
        "SELECT COUNT(*) FROM claims c "
        "JOIN delivery_states ds ON ds.slug = c.slug "
        "WHERE c.released_at IS NULL "
        "  AND c.marked_ready_at IS NOT NULL "
        "  AND ds.state = 'under_review' "
        "  AND NOT EXISTS ("
        "    SELECT 1 FROM review_views v "
        "    WHERE v.slug = c.slug "
        "      AND v.hf_user_id = ? "
        "      AND v.viewed_at >= c.marked_ready_at"
        "  )",
        (hf_user_id,),
    ).fetchone()[0])
