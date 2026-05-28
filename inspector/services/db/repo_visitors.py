"""``visitor_daily`` read/write — per-UTC-day traffic rollup.

``upsert_day`` accumulates a flushed bucket onto the day's row (one call per
hourly flush, inside a ``durable_transaction`` → one bucket upload/hour). Reads
use the autocommit reader.
"""

from __future__ import annotations

from .connection import get_conn

_COLS = ("signed_in_hits", "anon_hits", "unique_signed_in", "unique_anon")


def upsert_day(
    date: str,
    *,
    signed_in_hits: int,
    anon_hits: int,
    unique_signed_in: int,
    unique_anon: int,
) -> None:
    get_conn().execute(
        "INSERT INTO visitor_daily(date, signed_in_hits, anon_hits, "
        "unique_signed_in, unique_anon) VALUES (?,?,?,?,?) "
        "ON CONFLICT(date) DO UPDATE SET "
        "  signed_in_hits   = signed_in_hits   + excluded.signed_in_hits, "
        "  anon_hits        = anon_hits        + excluded.anon_hits, "
        "  unique_signed_in = unique_signed_in + excluded.unique_signed_in, "
        "  unique_anon      = unique_anon      + excluded.unique_anon",
        (date, signed_in_hits, anon_hits, unique_signed_in, unique_anon),
    )


def get_day(date: str) -> dict | None:
    row = get_conn().execute(
        "SELECT date, signed_in_hits, anon_hits, unique_signed_in, unique_anon "
        "FROM visitor_daily WHERE date = ?",
        (date,),
    ).fetchone()
    return dict(row) if row else None


def recent_days(limit: int) -> list[dict]:
    rows = get_conn().execute(
        "SELECT date, signed_in_hits, anon_hits, unique_signed_in, unique_anon "
        "FROM visitor_daily ORDER BY date DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
