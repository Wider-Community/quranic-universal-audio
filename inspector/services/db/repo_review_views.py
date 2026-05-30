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


def count_unviewed_for_user(hf_user_id: str) -> int:
    """Reviews-tab entries this admin hasn't viewed since their latest event.

    Two notification signals share one per-(user, slug) ``viewed_at`` cutoff:

    - **marked-ready** — an open claim's ``marked_ready_at`` (under_review only).
    - **job-finished** — ``delivery_states.last_job_finished_at``, stamped on a
      timestamps job's terminal state (success → released / Published bucket,
      failure → still under_review / Marked-ready bucket).

    A row counts when the LATER of the two events is newer than the admin's
    ``viewed_at`` (or unviewed). ISO-8601 UTC strings compare lexically. Single
    COUNT over ``delivery_states`` LEFT JOIN the open claim — cheap enough for
    the polled dot.
    """
    return int(get_conn().execute(
        "SELECT COUNT(*) FROM delivery_states ds "
        "LEFT JOIN claims c ON c.slug = ds.slug AND c.released_at IS NULL "
        "WHERE ("
        "    (ds.state = 'under_review' AND c.marked_ready_at IS NOT NULL) "
        "    OR ds.last_job_finished_at IS NOT NULL"
        "  ) "
        "  AND NOT EXISTS ("
        "    SELECT 1 FROM review_views v "
        "    WHERE v.slug = ds.slug "
        "      AND v.hf_user_id = ? "
        "      AND v.viewed_at >= MAX("
        "        IFNULL(CASE WHEN ds.state = 'under_review' "
        "                    THEN c.marked_ready_at END, ''), "
        "        IFNULL(ds.last_job_finished_at, '')"
        "      )"
        "  )",
        (hf_user_id,),
    ).fetchone()[0])
