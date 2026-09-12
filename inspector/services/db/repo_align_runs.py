"""Repository for ``align_runs`` — the native align pipeline's durable rows.

Writes require the caller's active transaction (``durable_transaction``). Reads
run on the shared connection. Rows are plain dicts; ``services/admin/
align_pipeline/runs.py`` projects them onto the wire model.
"""

from __future__ import annotations

from datetime import UTC, datetime

from . import _serde
from .connection import get_conn

ACTIVE_STATUSES = ("pending", "running", "failed")


def _now() -> str:
    return _serde.to_iso(datetime.now(UTC))


def get(run_id: str) -> dict | None:
    row = get_conn().execute("SELECT * FROM align_runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def active_for_slug(slug: str) -> dict | None:
    """The one pending/running/failed run for ``slug``, if any."""
    row = (
        get_conn()
        .execute(
            "SELECT * FROM align_runs WHERE slug = ? AND status IN ('pending','running','failed')",
            (slug,),
        )
        .fetchone()
    )
    return dict(row) if row else None


def latest_for_slug(slug: str) -> dict | None:
    row = (
        get_conn()
        .execute(
            "SELECT * FROM align_runs WHERE slug = ? ORDER BY started_at DESC LIMIT 1",
            (slug,),
        )
        .fetchone()
    )
    return dict(row) if row else None


def list_active() -> list[dict]:
    rows = (
        get_conn()
        .execute(
            "SELECT * FROM align_runs WHERE status IN ('pending','running','failed') "
            "ORDER BY started_at"
        )
        .fetchall()
    )
    return [dict(r) for r in rows]


def insert(
    *, run_id: str, slug: str, requested_by: str, params_json: str, chapters_total: int
) -> None:
    now = _now()
    get_conn().execute(
        "INSERT INTO align_runs (run_id, slug, stage, status, requested_by, params_json, "
        "acquire_job_id, attempt, chapters_total, last_error, started_at, updated_at, ended_at) "
        "VALUES (?, ?, 'acquire', 'pending', ?, ?, NULL, 1, ?, NULL, ?, ?, NULL)",
        (run_id, slug, requested_by, params_json, chapters_total, now, now),
    )


def update(run_id: str, **fields) -> None:
    """Set the given columns (+ ``updated_at``). Terminal statuses stamp ``ended_at``."""
    if not fields:
        return
    fields["updated_at"] = _now()
    if fields.get("status") in ("succeeded", "failed", "canceled"):
        fields.setdefault("ended_at", fields["updated_at"])
    cols = ", ".join(f"{k} = ?" for k in fields)
    get_conn().execute(
        f"UPDATE align_runs SET {cols} WHERE run_id = ?",  # noqa: S608 — column names are ours
        (*fields.values(), run_id),
    )
