"""Repository for the v2 release tables.

Three tables (migration 0014):

  - ``per_recitation_releases`` — TS gen + HF dataset push history per slug.
    Partial-unique on ``(track, slug) WHERE superseded_at IS NULL`` enforces
    one current row per (track, slug).
  - ``gh_releases``             — global GH release snapshots, one row per cut.
  - ``gh_release_recitations``  — frozen membership of each GH release. Rows
    are immutable post-cut; ``stale_since`` set on TS regen for the
    most-recent release.

All writers run inside the caller's active ``durable_transaction`` so
supersede/stale stamping commits atomically with the new INSERT.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import _serde
from .connection import get_conn


# ---------------------------------------------------------------------------
# per_recitation_releases
# ---------------------------------------------------------------------------


def insert_per_recitation_release(
    *,
    track: str,
    slug: str,
    version: str,
    produced_at: datetime,
    produced_by: str,
    produced_by_job_id: str | None = None,
    launched_by: str | None = None,
    external_uri: str | None = None,
    source_catalog_rev: str | None = None,
    validation_summary: dict[str, Any] | None = None,
) -> int:
    """Insert a new release row. Caller must supersede the prior current row
    in the same transaction (see ``supersede_current``)."""
    cur = get_conn().execute(
        "INSERT INTO per_recitation_releases("
        " track, slug, version, produced_at, produced_by, produced_by_job_id,"
        " launched_by, external_uri, source_catalog_rev, validation_summary"
        ") VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            track, slug, version,
            _serde.to_iso(produced_at), produced_by, produced_by_job_id,
            launched_by, external_uri, source_catalog_rev,
            _serde.json_dumps(validation_summary) if validation_summary else None,
        ),
    )
    return int(cur.lastrowid)


def supersede_current(track: str, slug: str, *, except_id: int, at: datetime) -> int:
    """Mark prior current rows for (track, slug) as superseded, excluding the
    just-inserted row. Returns the number of rows updated.

    Same partial-unique pattern as ``ux_role_active`` / ``ux_claim_open_slug``.
    """
    cur = get_conn().execute(
        "UPDATE per_recitation_releases SET superseded_at = ? "
        "WHERE track = ? AND slug = ? AND id != ? AND superseded_at IS NULL",
        (_serde.to_iso(at), track, slug, except_id),
    )
    return int(cur.rowcount)


def current_release(track: str, slug: str) -> dict | None:
    """Return the current (non-superseded) row for ``(track, slug)`` or None."""
    r = get_conn().execute(
        "SELECT * FROM per_recitation_releases "
        "WHERE track = ? AND slug = ? AND superseded_at IS NULL",
        (track, slug),
    ).fetchone()
    return dict(r) if r else None


def stamp_stale_on_ts_regen(slug: str, *, at: datetime) -> int:
    """Mark the current ``hf`` row for ``slug`` (if any) as stale, AND mark
    that slug's row in the most-recent ``gh_releases`` (if it was a member)
    as stale. Returns the total number of stale stamps applied.

    Called by ``ts.complete()`` (via the legacy ``complete_timestamps_job``
    after this lands in Phase 3) inside the same durable_transaction as the
    ``per_recitation_releases(track='ts')`` insert.
    """
    iso = _serde.to_iso(at)
    n = 0
    cur = get_conn().execute(
        "UPDATE per_recitation_releases SET stale_since = ? "
        "WHERE track = 'hf' AND slug = ? "
        "AND superseded_at IS NULL AND stale_since IS NULL",
        (iso, slug),
    )
    n += int(cur.rowcount)
    cur = get_conn().execute(
        "UPDATE gh_release_recitations SET stale_since = ? "
        "WHERE slug = ? AND stale_since IS NULL "
        "AND release_id = (SELECT id FROM gh_releases "
        "                  WHERE superseded_at IS NULL "
        "                  ORDER BY id DESC LIMIT 1)",
        (iso, slug),
    )
    n += int(cur.rowcount)
    return n


# ---------------------------------------------------------------------------
# gh_releases + gh_release_recitations
# ---------------------------------------------------------------------------


def insert_gh_release(
    *,
    version: str,
    produced_at: datetime,
    produced_by: str,
    produced_by_job_id: str | None = None,
    launched_by: str | None = None,
    external_uri: str | None = None,
    source_catalog_rev: str | None = None,
    operator_note: str | None = None,
    validation_summary: dict[str, Any] | None = None,
) -> int:
    cur = get_conn().execute(
        "INSERT INTO gh_releases("
        " version, produced_at, produced_by, produced_by_job_id, launched_by,"
        " external_uri, source_catalog_rev, operator_note, validation_summary"
        ") VALUES (?,?,?,?,?,?,?,?,?)",
        (
            version, _serde.to_iso(produced_at), produced_by, produced_by_job_id,
            launched_by, external_uri, source_catalog_rev, operator_note,
            _serde.json_dumps(validation_summary) if validation_summary else None,
        ),
    )
    return int(cur.lastrowid)


def supersede_prior_gh_releases(*, except_id: int, at: datetime) -> int:
    """Mark prior non-superseded gh_releases rows as superseded."""
    cur = get_conn().execute(
        "UPDATE gh_releases SET superseded_at = ? "
        "WHERE id != ? AND superseded_at IS NULL",
        (_serde.to_iso(at), except_id),
    )
    return int(cur.rowcount)


def latest_gh_release() -> dict | None:
    """Most-recent non-superseded GH release row or None."""
    r = get_conn().execute(
        "SELECT * FROM gh_releases WHERE superseded_at IS NULL "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(r) if r else None


def insert_gh_release_recitation(
    *,
    release_id: int,
    slug: str,
    catalog_snapshot: dict[str, Any],
    zip_sha256: str,
    zip_bytes: int,
    coverage_ayahs: int,
    content_hash: str | None,
    ts_version: str,
    change_kind: str,
) -> None:
    get_conn().execute(
        "INSERT INTO gh_release_recitations("
        " release_id, slug, catalog_snapshot, zip_sha256, zip_bytes,"
        " coverage_ayahs, content_hash, ts_version, change_kind"
        ") VALUES (?,?,?,?,?,?,?,?,?)",
        (
            release_id, slug, _serde.json_dumps(catalog_snapshot),
            zip_sha256, zip_bytes, coverage_ayahs, content_hash,
            ts_version, change_kind,
        ),
    )


def gh_release_recitations(release_id: int) -> list[dict]:
    rows = get_conn().execute(
        "SELECT * FROM gh_release_recitations WHERE release_id = ? ORDER BY slug",
        (release_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def latest_gh_release_member(slug: str) -> dict | None:
    """Most-recent gh_release_recitations row for ``slug`` across all releases."""
    r = get_conn().execute(
        "SELECT grr.* FROM gh_release_recitations grr "
        "JOIN gh_releases gr ON gr.id = grr.release_id "
        "WHERE grr.slug = ? AND gr.superseded_at IS NULL "
        "ORDER BY gr.id DESC LIMIT 1",
        (slug,),
    ).fetchone()
    return dict(r) if r else None
