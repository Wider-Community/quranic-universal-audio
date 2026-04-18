/**
 * Segments tab — saved filter view (for "Back to results" banner).
 *
 * `backBannerVisible` derived is an alias for "view is saved" — consumed by
 * Navigation.svelte to conditionally render the back-banner.
 *
 * Cross-cutting: Navigation.svelte subscribes to `activeFilters` and clears
 * `savedFilterView` when filters become non-empty. Other writers (reciter
 * change, explicit "back" click, explicit "clear filters") clear it directly
 * via `.set(null)`.
 */

import { derived, writable } from 'svelte/store';

import type { SegActiveFilter } from './filters';

/** Saved UI snapshot so Navigation.svelte can restore a filter + scroll view. */
export interface SegSavedFilterView {
    filters: SegActiveFilter[];
    chapter: string;
    verse: string;
    scrollTop: number;
}

/** Writable — the saved view, or null when no "back to results" is available. */
export const savedFilterView = writable<SegSavedFilterView | null>(null);

/** Derived boolean: whether to render the back-to-results banner. */
export const backBannerVisible = derived(
    savedFilterView,
    ($s) => $s !== null,
);

/** The displayed-segment index that should be scrolled into view. Cleared
 *  to null by SegmentRow after it observes the match and calls
 *  scrollIntoView. */
export const targetSegmentIndex = writable<number | null>(null);

/** Set of displayed-segment indices that should have the transient flash
 *  (visual highlight after jump). Cleared by setTimeout after ~2 seconds.
 *  SegmentRow ORs this with isPlaying to drive the `.playing` class. */
export const flashSegmentIndices = writable<Set<number>>(new Set());

/** One-shot scroll-top target for the seg-list container. Set by
 *  _restoreFilterView, consumed + cleared by SegmentsList's afterUpdate. */
export const pendingScrollTop = writable<number | null>(null);
