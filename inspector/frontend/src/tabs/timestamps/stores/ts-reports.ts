/**
 * Timestamps-tab report state for the current reciter.
 *
 * Holds the per-verse open/resolved counts powering the footer Report button's
 * "reported" highlight. Loaded on reciter change and refreshed after the local
 * user files or removes a report. Public data — populated for everyone.
 *
 * The per-verse report list (categories + the caller's own reports) is fetched
 * on demand by the drop-up, not cached here.
 */
import { derived, writable } from 'svelte/store';

import type { TsReport, TsReportVerseCount } from '../../../lib/types/generated/schemas';
import { getReciterReports, getVerseReports } from '../services/reports-client';

export const reportedVerses = writable<TsReportVerseCount[]>([]);

/** Every report on the currently-loaded verse — drives the in-grid public flags
 *  (red border + tooltip) for ALL viewers, and seeds report mode's own flags.
 *  Loaded on verse change. */
export const currentVerseReports = writable<TsReport[]>([]);

// Stale-load guard: tracks the most-recently requested verse token so a slow
// fetch for a superseded verse can't overwrite the current verse's data.
let _latestVerseKey = '';

/** Reload the loaded verse's reports. Silent on failure (flags are non-critical). */
export async function loadVerseReports(slug: string, verseKey: string): Promise<void> {
    if (!slug || !verseKey) {
        currentVerseReports.set([]);
        return;
    }
    const token = `${slug}|${verseKey}`;
    _latestVerseKey = token;
    try {
        const doc = await getVerseReports(slug, verseKey);
        if (token !== _latestVerseKey) return;
        currentVerseReports.set(doc.reports ?? []);
    } catch {
        if (token !== _latestVerseKey) return;
        currentVerseReports.set([]);
    }
}

/** Verse keys that currently carry at least one OPEN report. */
export const openReportedVerseKeys = derived(reportedVerses, ($v) => {
    const s = new Set<string>();
    for (const r of $v) if (r.open_count > 0) s.add(r.verse_key);
    return s;
});

/** Reload the reported-verse counts for a reciter. Silent on failure (the
 *  highlight is non-critical). Guard against a stale reciter switch in callers. */
export async function loadReciterReports(slug: string): Promise<void> {
    if (!slug) {
        reportedVerses.set([]);
        return;
    }
    try {
        const doc = await getReciterReports(slug);
        reportedVerses.set(doc.reports ?? []);
    } catch {
        reportedVerses.set([]);
    }
}
