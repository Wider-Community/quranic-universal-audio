/** Compact formatters for the admin Users panel (match the mockup). */

/** "Sep 3, 2025" — or "—" when absent. */
export function fmtDate(iso?: string | null): string {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/** Compact relative age: "now" / "32m" / "4h" / "9d". "—" when absent. */
export function compactAgo(iso?: string | null): string {
    if (!iso) return '—';
    const t = new Date(iso).getTime();
    if (Number.isNaN(t)) return '—';
    const s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 60) return 'now';
    if (s < 3600) return `${Math.floor(s / 60)}m`;
    if (s < 86400) return `${Math.floor(s / 3600)}h`;
    return `${Math.floor(s / 86400)}d`;
}

/** Whole-days since `iso`, or null when absent — for the stalled-claim flag. */
export function daysSince(iso?: string | null): number | null {
    if (!iso) return null;
    const t = new Date(iso).getTime();
    if (Number.isNaN(t)) return null;
    return (Date.now() - t) / 86_400_000;
}

/** Turnaround seconds → "2.4d" / "3.0h" / "12m". "—" when absent. */
export function fmtDuration(sec?: number | null): string {
    if (sec == null) return '—';
    if (sec >= 86400) return `${(sec / 86400).toFixed(1)}d`;
    if (sec >= 3600) return `${(sec / 3600).toFixed(1)}h`;
    return `${Math.round(sec / 60)}m`;
}
