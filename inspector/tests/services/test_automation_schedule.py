"""Automation schedule math — never-run, catch-up, interval, tz fallback."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.admin.automation import schedule


def _now() -> datetime:
    return datetime(2026, 6, 9, 12, 0, tzinfo=UTC)


def test_never_run_is_not_due_and_fires_at_next_occurrence():
    now = _now()
    assert (
        schedule.is_due(
            last_run_at=None,
            interval_days=7,
            time_of_day="09:00",
            timezone="Australia/Sydney",
            now_utc=now,
        )
        is False
    )
    nxt = schedule.next_fire_at(
        last_run_at=None,
        interval_days=7,
        time_of_day="09:00",
        timezone="Australia/Sydney",
        now_utc=now,
    )
    # The first fire is the upcoming HH:MM occurrence — strictly future, ≤ 24h out.
    assert now < nxt <= now + timedelta(days=1)


def test_missed_window_is_due_on_catch_up():
    now = _now()
    last = now - timedelta(days=8)  # interval is 7 → overdue by ~1 day
    assert (
        schedule.is_due(
            last_run_at=last,
            interval_days=7,
            time_of_day="09:00",
            timezone="Australia/Sydney",
            now_utc=now,
        )
        is True
    )


def test_within_interval_is_not_due():
    now = _now()
    last = now - timedelta(hours=2)
    assert (
        schedule.is_due(
            last_run_at=last,
            interval_days=7,
            time_of_day="09:00",
            timezone="Australia/Sydney",
            now_utc=now,
        )
        is False
    )


def test_unknown_timezone_falls_back_without_raising():
    now = _now()
    nxt = schedule.next_fire_at(
        last_run_at=None,
        interval_days=1,
        time_of_day="09:00",
        timezone="Not/AZone",
        now_utc=now,
    )
    assert isinstance(nxt, datetime)
