/**
 * Timestamps-tab report client.
 *
 * Backed by `/api/ts/<slug>/reports*` (see `inspector/routes/timestamps/
 * reports.py`). Public reads need no auth; writes go through a same-origin
 * `fetch` with the cookie. Anonymous callers pass an `anonToken` (from
 * `lib/utils/anon-token`) so the backend can key their report and let them
 * edit/delete it later. Reads also pass an EXISTING anon token (never minting
 * one) so an anonymous reporter sees their own non-public (tajweed/phoneme)
 * flags + counts, which the backend hides from other visitors.
 */

import { get } from 'svelte/store';

import { fetchJson } from '../../../lib/api';
import { currentUser } from '../../../lib/stores/current-user';
import type {
    TsReciterReports,
    TsReport,
    TsReportBatchCreateRequest,
    TsReportBatchResult,
    TsReportCreateRequest,
    TsVerseReports,
} from '../../../lib/types/generated/schemas';
import { peekAnonToken } from '../../../lib/utils/anon-token';

/** `?anon_token=…` for an anonymous browser that already has a token, else ''. */
function anonQuery(): string {
    if (get(currentUser).hf_user_id !== null) return '';
    const t = peekAnonToken();
    return t ? `?anon_token=${encodeURIComponent(t)}` : '';
}

/** Reported-verse counts for the whole reciter (drives the button highlight). */
export async function getReciterReports(slug: string): Promise<TsReciterReports> {
    return fetchJson<TsReciterReports>(
        `/api/ts/${encodeURIComponent(slug)}/reports${anonQuery()}`,
        { credentials: 'same-origin' },
    );
}

/** Every report on one verse (drives the per-category highlight + composer). */
export async function getVerseReports(slug: string, verseKey: string): Promise<TsVerseReports> {
    return fetchJson<TsVerseReports>(
        `/api/ts/${encodeURIComponent(slug)}/reports/${encodeURIComponent(verseKey)}${anonQuery()}`,
        { credentials: 'same-origin' },
    );
}

/** Create (or update, on a repeat of the same category+target) the caller's report. */
export async function createReport(
    slug: string,
    body: TsReportCreateRequest,
): Promise<TsReport & { error?: string }> {
    return fetchJson<TsReport & { error?: string }>(`/api/ts/${encodeURIComponent(slug)}/reports`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
}

/** Submit many staged annotations on one verse in a single transaction. */
export async function createReportsBatch(
    slug: string,
    body: TsReportBatchCreateRequest,
): Promise<TsReportBatchResult & { error?: string }> {
    return fetchJson<TsReportBatchResult & { error?: string }>(
        `/api/ts/${encodeURIComponent(slug)}/reports/batch`,
        {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        },
    );
}

/** Remove the caller's own report (soft-deleted server-side — gone from views). */
export async function deleteReport(
    slug: string,
    reportId: number,
    anonToken?: string | null,
): Promise<boolean> {
    const q = anonToken ? `?anon_token=${encodeURIComponent(anonToken)}` : '';
    const res = await fetchJson<{ ok?: boolean }>(
        `/api/ts/${encodeURIComponent(slug)}/reports/${reportId}${q}`,
        { method: 'DELETE', credentials: 'same-origin' },
    );
    return !!res?.ok;
}
