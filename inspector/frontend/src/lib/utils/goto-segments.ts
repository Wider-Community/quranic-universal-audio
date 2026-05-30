/**
 * Deep-link into the Segments tab with a specific reciter pre-selected.
 *
 * Extracted from the admin Reviews-row "Segments" action so every surface
 * (dashboard reciter modal, edit-affordance popover, ReviewsRow) shares one
 * move. `SegmentsTab.svelte` reacts to an out-of-band `selectedReciter` set
 * (it binds the reciter-task + loads the chapter), so setting the store is all
 * that's needed — no event dispatch. We persist the slug to localStorage first
 * so a refresh lands back on the same reciter.
 */

import { setActiveTab } from './active-tab';
import { LS_KEYS, TAB_NAMES } from './constants';
import { selectedReciter } from '../../tabs/segments/stores/chapter';

export function gotoSegments(slug: string): void {
    if (!slug) return;
    try {
        localStorage.setItem(LS_KEYS.SEG_RECITER, slug);
    } catch {
        /* localStorage unavailable — the store-set still works this session */
    }
    selectedReciter.set(slug);
    setActiveTab(TAB_NAMES.SEGMENTS);
}
