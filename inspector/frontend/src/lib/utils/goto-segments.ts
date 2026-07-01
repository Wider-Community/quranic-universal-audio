/**
 * Deep-link into the Segments tab with a specific reciter pre-selected.
 *
 * Extracted from the admin Reviews-row "Segments" action so every surface
 * (dashboard reciter modal, edit-affordance popover, ReviewsRow) shares one
 * move. `SegmentsTab.svelte` reacts to an out-of-band `selectedReciter` set
 * (it binds the reciter-task + loads the chapter), so setting the store is all
 * that's needed — no event dispatch. We persist the slug to localStorage first
 * so a refresh lands back on the same reciter.
 *
 * An optional `deepLink` carries a follow-up focus intent (e.g. open the
 * Flagged accordion and scroll to a flagged segment) that `ValidationPanel`
 * consumes once the reciter's data has loaded — see `pendingSegmentsDeepLink`.
 */

import { writable } from 'svelte/store';

import { selectedReciter } from '../../tabs/segments/stores/chapter';
import { setActiveTab } from './active-tab';
import { LS_KEYS, TAB_NAMES } from './constants';

/** A follow-up focus intent for the Segments tab, applied after the reciter's
 *  segments load. Cross-tab handoff: set by a navigating surface (e.g. the
 *  notifications rail, or the Timestamps footer "open in Segments" redirect),
 *  consumed exactly once by `ValidationPanel` (flag intents) or `SegmentsTab`
 *  (`focusVerse` / `openMarkReadyReview`). */
export interface SegmentsDeepLink {
    /** Open the "Flagged Issues" accordion once flagged segments are present. */
    openFlagged?: boolean;
    /** Scroll the flagged segment with this uid into view inside the accordion. */
    focusFlaggedUid?: string;
    /** Open the read-only mark-ready review modal once the reciter task loads. */
    openMarkReadyReview?: boolean;
    /** Switch to this verse's chapter and scroll its first segment row into
     *  view, once the target reciter's corpus + chapter data have loaded.
     *  `slug` guards the consumer against firing while the previous reciter's
     *  corpus is still resident during a switch. Consumed by `SegmentsTab`. */
    focusVerse?: { slug: string; chapter: number; verse: number };
}

export const pendingSegmentsDeepLink = writable<SegmentsDeepLink | null>(null);

export function gotoSegments(slug: string, deepLink?: SegmentsDeepLink): void {
    if (!slug) return;
    // Replace any prior intent (a plain navigation clears a stale deep-link).
    pendingSegmentsDeepLink.set(deepLink ?? null);
    try {
        localStorage.setItem(LS_KEYS.SEG_RECITER, slug);
    } catch {
        /* localStorage unavailable — the store-set still works this session */
    }
    selectedReciter.set(slug);
    setActiveTab(TAB_NAMES.SEGMENTS);
}
