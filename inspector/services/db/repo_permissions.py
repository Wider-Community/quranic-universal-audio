"""Repository for ``permission_overrides`` — owner-set deviations from the
capability registry defaults.

Stores ONLY rows that differ from the baseline (``qua_shared/schemas/
capabilities.py``). An absent ``(capability_id, tier)`` row means "use the
default"; ``clear_override`` (a DELETE) resets a cell to default. The resolver
(``services/auth/capabilities.py``) overlays these rows on the defaults.

Write primitives operate on the active transaction connection — the route
layer wraps ``set_override`` / ``clear_override`` in ``durable_transaction``
and pairs each with a ``repo_transitions.append`` audit. Reads are used by the
db_seq-keyed matrix cache, so they run on the shared read connection.
"""

from __future__ import annotations

from datetime import datetime

from . import _serde
from .connection import get_conn


def all_overrides() -> list[tuple[str, str, bool]]:
    """Every override row as ``(capability_id, tier, allowed)``. Drives the
    resolver's overlay on top of the registry defaults."""
    rows = (
        get_conn()
        .execute("SELECT capability_id, tier, allowed FROM permission_overrides")
        .fetchall()
    )
    return [(r[0], r[1], bool(r[2])) for r in rows]


def get_override(capability_id: str, tier: str) -> bool | None:
    """The stored override for one cell, or None when at the default. Used to
    compute the before/after for the toggle audit."""
    row = (
        get_conn()
        .execute(
            "SELECT allowed FROM permission_overrides WHERE capability_id = ? AND tier = ?",
            (capability_id, tier),
        )
        .fetchone()
    )
    return bool(row[0]) if row is not None else None


def set_override(
    *,
    capability_id: str,
    tier: str,
    allowed: bool,
    set_by: str,
    now: datetime | None = None,
) -> None:
    """Upsert one override cell (idempotent)."""
    ts = _serde.to_iso(now or _serde.now())
    get_conn().execute(
        "INSERT INTO permission_overrides(capability_id, tier, allowed, set_by, set_at) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(capability_id, tier) DO UPDATE SET "
        "  allowed = excluded.allowed, set_by = excluded.set_by, set_at = excluded.set_at",
        (capability_id, tier, 1 if allowed else 0, set_by, ts),
    )


def clear_override(*, capability_id: str, tier: str) -> None:
    """Remove the override cell, resetting it to the registry default."""
    get_conn().execute(
        "DELETE FROM permission_overrides WHERE capability_id = ? AND tier = ?",
        (capability_id, tier),
    )
