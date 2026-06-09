"""Owner-timezone interval scheduling for the cut / publish automations.

"Every N days at HH:MM in <timezone>" → the next UTC fire instant. The
``last_run_at`` guard makes a missed window fire exactly once on catch-up
(restart / Space-down), and DST is handled by ``zoneinfo``. An unknown timezone
or malformed time degrades to a safe default rather than crashing the tick.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_DEFAULT_HOUR = 9


def _safe_zone(tz_name: str) -> tzinfo:
    """Resolve an IANA tz name, falling back to UTC (e.g. Windows without
    ``tzdata``, or a bad name). UTC is always available."""
    try:
        return ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 — ZoneInfoNotFoundError or missing tzdata
        logger.warning("automation: unknown timezone %r — using UTC", tz_name)
        return UTC


def _parse_hhmm(s: str) -> tuple[int, int]:
    try:
        hh, mm = s.split(":", 1)
        return int(hh), int(mm)
    except Exception:  # noqa: BLE001 — validated upstream; this is defence in depth
        logger.warning("automation: bad time_of_day %r — using %02d:00", s, _DEFAULT_HOUR)
        return _DEFAULT_HOUR, 0


def next_fire_at(
    *,
    last_run_at: datetime | None,
    interval_days: int,
    time_of_day: str,
    timezone: str,
    now_utc: datetime,
) -> datetime:
    """The next scheduled fire instant (UTC).

    Never run yet → the next ``time_of_day`` occurrence at-or-after ``now`` (so a
    freshly-enabled schedule fires at the upcoming HH:MM, not a full interval
    later). Otherwise → ``time_of_day`` on the date ``interval_days`` after the
    last fire's local date.
    """
    tz = _safe_zone(timezone)
    hh, mm = _parse_hhmm(time_of_day)
    if last_run_at is None:
        now_local = now_utc.astimezone(tz)
        candidate = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate <= now_local:
            candidate += timedelta(days=1)
    else:
        last_local = last_run_at.astimezone(tz)
        fire_date = (last_local + timedelta(days=interval_days)).date()
        candidate = datetime.combine(fire_date, time(hh, mm), tzinfo=tz)
    return candidate.astimezone(UTC)


def is_due(
    *,
    last_run_at: datetime | None,
    interval_days: int,
    time_of_day: str,
    timezone: str,
    now_utc: datetime,
) -> bool:
    """Whether ``now`` has reached the next scheduled fire."""
    return now_utc >= next_fire_at(
        last_run_at=last_run_at,
        interval_days=interval_days,
        time_of_day=time_of_day,
        timezone=timezone,
        now_utc=now_utc,
    )
