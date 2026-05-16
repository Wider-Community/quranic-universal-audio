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

const SECOND = 1;
const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;
const MONTH = 30 * DAY;
const YEAR = 365 * DAY;

function pluralize(n: number, unit: string): string {
    return `${n} ${unit}${n === 1 ? '' : 's'} ago`;
}

export function relativeTime(iso: string, now: Date = new Date()): string {
    const then = new Date(iso);
    if (Number.isNaN(then.getTime())) return iso;
    const deltaSec = Math.max(0, Math.floor((now.getTime() - then.getTime()) / 1000));

    if (deltaSec < MINUTE) return 'just now';
    if (deltaSec < HOUR) return pluralize(Math.floor(deltaSec / MINUTE), 'minute');
    if (deltaSec < DAY) return pluralize(Math.floor(deltaSec / HOUR), 'hour');
    if (deltaSec < 2 * DAY) return 'yesterday';
    if (deltaSec < WEEK) return pluralize(Math.floor(deltaSec / DAY), 'day');
    if (deltaSec < MONTH) return pluralize(Math.floor(deltaSec / WEEK), 'week');
    if (deltaSec < YEAR) return pluralize(Math.floor(deltaSec / MONTH), 'month');
    return pluralize(Math.floor(deltaSec / YEAR), 'year');
}
