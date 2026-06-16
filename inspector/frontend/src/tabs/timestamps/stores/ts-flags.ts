/**
 * Timestamps-tab verse flags for the current reciter.
 *
 * Holds the flagged-verse counts (verse_key → comment count) powering the
 * "Flagged issues" accordion and the footer Report button's flagged state.
 * Loaded by `TimestampsTab` on reciter change and refreshed after the local
 * user flags/unflags a verse. Public data — populated for everyone.
 */
import { writable } from 'svelte/store';

import type { TsFlagVerseCount } from '../../../lib/types/generated/schemas';
import { getReciterFlags } from '../services/flags-client';

export const tsFlaggedVerses = writable<TsFlagVerseCount[]>([]);

/** Reload the flagged-verse list for a reciter. Silent on failure (the rail is
 *  non-critical). Guarded by the caller against a stale reciter switch. */
export async function loadTsFlags(slug: string): Promise<void> {
    if (!slug) {
        tsFlaggedVerses.set([]);
        return;
    }
    try {
        const doc = await getReciterFlags(slug);
        tsFlaggedVerses.set(doc.flags ?? []);
    } catch {
        tsFlaggedVerses.set([]);
    }
}
