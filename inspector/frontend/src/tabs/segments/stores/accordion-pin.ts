/**
 * Pin state for the currently-open validation accordion.
 *
 * Captured when the accordion opens; preserves the open-time list of items
 * (by key) so autosave-driven `segValidation` refreshes don't yank cards out
 * from under the user mid-interaction. Counts stay live (separate reactive
 * path); only the rendered list inside the open accordion is pinned.
 *
 * Cleared on user-visible "boundary" events: accordion close, opening a
 * different accordion, chapter change, reciter change, tab switch away from
 * Segments.
 */

import { writable } from 'svelte/store';

import type { SegValAnyItem } from '../../../lib/types/generated/schemas';

export interface AccordionPin {
    /** Category type currently pinned (e.g. 'missing_words', 'repetitions'). */
    category: string;
    /** Stable composite keys in open-time order. */
    keys: string[];
    /** Snapshot copy keyed by composite key — used to render items that have
     *  fallen out of the live `visibleItems` since the pin (resolved by edit). */
    items: Record<string, SegValAnyItem>;
}

export const accordionPin = writable<AccordionPin | null>(null);

/**
 * Snapshot the currently-visible items for a category. `keyOf` mirrors the
 * `{#each}` keying so live lookups inside the render path stay in sync.
 */
export function pinAccordion(
    category: string,
    visibleItems: readonly SegValAnyItem[],
    keyOf: (item: SegValAnyItem, kind: string) => string,
): void {
    const keys: string[] = [];
    const items: Record<string, SegValAnyItem> = {};
    for (const it of visibleItems) {
        const k = keyOf(it, category);
        if (k in items) continue;
        keys.push(k);
        items[k] = it;
    }
    accordionPin.set({ category, keys, items });
}

export function clearAccordionPin(): void {
    accordionPin.set(null);
}
