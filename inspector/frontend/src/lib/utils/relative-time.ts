/**
 * Human-friendly relative time formatter for activity feed cards and
 * detail-page timestamps.
 *
 * Returns short, restrained labels — "3 hours ago", "yesterday",
 * "2 weeks ago" — that match the Phase 6 mockup voice (catalog dignity,
 * no chatty filler).
 *
 * Falls back to the input string when given an unparseable date so
 * upstream rendering still succeeds.
 */

import * as m from '$lib/paraglide/messages';

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;
const MONTH = 30 * DAY;
const YEAR = 365 * DAY;

export function relativeTime(iso: string, now: Date = new Date()): string {
    const then = new Date(iso);
    if (Number.isNaN(then.getTime())) return iso;
    const deltaSec = Math.max(0, Math.floor((now.getTime() - then.getTime()) / 1000));

    if (deltaSec < MINUTE) return m.common_relative_time_just_now();
    if (deltaSec < HOUR) return m.common_relative_time_minutes_ago({ count: Math.floor(deltaSec / MINUTE) });
    if (deltaSec < DAY) return m.common_relative_time_hours_ago({ count: Math.floor(deltaSec / HOUR) });
    if (deltaSec < 2 * DAY) return m.common_relative_time_yesterday();
    if (deltaSec < WEEK) return m.common_relative_time_days_ago({ count: Math.floor(deltaSec / DAY) });
    if (deltaSec < MONTH) return m.common_relative_time_weeks_ago({ count: Math.floor(deltaSec / WEEK) });
    if (deltaSec < YEAR) return m.common_relative_time_months_ago({ count: Math.floor(deltaSec / MONTH) });
    return m.common_relative_time_years_ago({ count: Math.floor(deltaSec / YEAR) });
}
