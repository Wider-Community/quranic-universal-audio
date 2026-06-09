"""Repository for the release-automation config + runtime state.

Two tables (migration ``0019_automation.sql``):

- ``automation_config`` — a single-row JSON blob holding the owner's
  ``AutomationConfig``. ``get_config_json`` / ``set_config_json`` are the only
  accessors; ``services/admin/automation/config.py`` wraps them with the
  Pydantic model + a db_seq-keyed cache.
- ``automation_state`` — per-automation runtime (last fire time + result +
  computed next run). ``record_run`` upserts one automation's row; the engine
  calls it ONLY when an automation acts or a schedule advances, so idle ticks
  never write (no per-tick bucket upload).

Write primitives operate on the active transaction connection — the route /
engine layer wraps them in ``durable_transaction``. Reads run on the shared
read connection.
"""

from __future__ import annotations

from datetime import datetime

from . import _serde
from .connection import get_conn

_CONFIG_ID = 1


def get_config_json() -> str | None:
    """The persisted ``AutomationConfig`` JSON blob, or None when never set."""
    row = (
        get_conn()
        .execute("SELECT config_json FROM automation_config WHERE id = ?", (_CONFIG_ID,))
        .fetchone()
    )
    return row[0] if row is not None else None


def set_config_json(config_json: str, *, updated_by: str, now: datetime | None = None) -> None:
    """Upsert the single config blob (idempotent)."""
    ts = _serde.to_iso(now or _serde.now())
    get_conn().execute(
        "INSERT INTO automation_config(id, config_json, updated_at, updated_by) "
        "VALUES (?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "  config_json = excluded.config_json, updated_at = excluded.updated_at, "
        "  updated_by = excluded.updated_by",
        (_CONFIG_ID, config_json, ts, updated_by),
    )


def all_state() -> list[dict]:
    """Every per-automation runtime row, for the FE status line."""
    rows = (
        get_conn()
        .execute(
            "SELECT automation_id, last_run_at, last_status, last_detail "
            "FROM automation_state ORDER BY automation_id"
        )
        .fetchall()
    )
    return [
        {"automation_id": r[0], "last_run_at": r[1], "last_status": r[2], "last_detail": r[3]}
        for r in rows
    ]


def get_state(automation_id: str) -> dict | None:
    """One automation's runtime row, or None when it has never run."""
    r = (
        get_conn()
        .execute(
            "SELECT automation_id, last_run_at, last_status, last_detail "
            "FROM automation_state WHERE automation_id = ?",
            (automation_id,),
        )
        .fetchone()
    )
    if r is None:
        return None
    return {"automation_id": r[0], "last_run_at": r[1], "last_status": r[2], "last_detail": r[3]}


def record_run(
    automation_id: str,
    *,
    status: str,
    detail: str | None = None,
    last_run_at: datetime | None = None,
    now: datetime | None = None,
) -> None:
    """Upsert one automation's runtime row.

    ``status`` is ``launched`` / ``skipped`` / ``error``. ``last_run_at`` stamps
    the actual fire time (advances the scheduled cadence); pass None to leave the
    prior value untouched (e.g. a launch error that must not advance the cadence).
    """
    updated = _serde.to_iso(now or _serde.now())
    last_iso = _serde.to_iso(last_run_at)
    # COALESCE keeps the prior last_run_at when the caller passes None (the
    # error path must not advance the cadence).
    get_conn().execute(
        "INSERT INTO automation_state"
        "  (automation_id, last_run_at, last_status, last_detail, updated_at) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(automation_id) DO UPDATE SET "
        "  last_run_at = COALESCE(excluded.last_run_at, automation_state.last_run_at), "
        "  last_status = excluded.last_status, "
        "  last_detail = excluded.last_detail, "
        "  updated_at  = excluded.updated_at",
        (automation_id, last_iso, status, detail, updated),
    )
