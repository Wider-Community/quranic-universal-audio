/**
 * Timestamps-tab verse-flag client.
 *
 * Backed by `/api/ts/<slug>/flags*` (see `inspector/routes/timestamps/flags.py`).
 * Public reads need no auth; writes go through a same-origin `fetch` with the
 * cookie. Anonymous callers pass an `anonToken` (from `lib/utils/anon-token`)
 * so the backend can key their flag and let them edit/delete it later.
 */

import { fetchJson } from '../../../lib/api';
import type {
    TsFlagComment,
    TsReciterFlags,
    TsVerseFlags,
} from '../../../lib/types/generated/schemas';

/** Flagged-verse pills + counts for the accordion. */
export async function getReciterFlags(slug: string): Promise<TsReciterFlags> {
    return fetchJson<TsReciterFlags>(`/api/ts/${encodeURIComponent(slug)}/flags`, {
        credentials: 'same-origin',
    });
}

/** All comments on one verse (for the flag modal). */
export async function getVerseFlags(
    slug: string,
    verseKey: string,
    anonToken?: string | null,
): Promise<TsVerseFlags> {
    const q = anonToken ? `?anon_token=${encodeURIComponent(anonToken)}` : '';
    return fetchJson<TsVerseFlags>(
        `/api/ts/${encodeURIComponent(slug)}/flags/${encodeURIComponent(verseKey)}${q}`,
        { credentials: 'same-origin' },
    );
}

/** Create or update the caller's comment on a verse. */
export async function createTsFlag(
    slug: string,
    verseKey: string,
    comment: string | null,
    anonToken?: string | null,
): Promise<TsFlagComment & { error?: string }> {
    return fetchJson<TsFlagComment & { error?: string }>(
        `/api/ts/${encodeURIComponent(slug)}/flags`,
        {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ verse_key: verseKey, comment, anon_token: anonToken ?? null }),
        },
    );
}

/** Delete the caller's own comment on a verse. */
export async function deleteTsFlag(
    slug: string,
    verseKey: string,
    anonToken?: string | null,
): Promise<boolean> {
    const q = anonToken ? `?anon_token=${encodeURIComponent(anonToken)}` : '';
    const res = await fetchJson<{ ok?: boolean }>(
        `/api/ts/${encodeURIComponent(slug)}/flags/${encodeURIComponent(verseKey)}${q}`,
        { method: 'DELETE', credentials: 'same-origin' },
    );
    return !!res?.ok;
}
