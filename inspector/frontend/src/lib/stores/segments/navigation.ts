/**
 * Segments tab — saved filter view (for "Back to results" banner).
 *
 * Replaces the Stage-1 `state._segSavedFilterView` field. The
 * `backBannerVisible` derived is an alias for "view is saved" — consumed by
 * Navigation.svelte to conditionally render the back-banner.
 *
 * Cross-cutting: filter application in FiltersBar + reciter change in
 * SegmentsTab clear the saved view. We use option (a) from the store-bindings
 * matrix cross-cutting-warnings: Navigation.svelte subscribes to
 * `activeFilters` and clears `savedFilterView` when filters become non-empty
 * (see Navigation.svelte). Other writers (reciter change, explicit "back"
 * click, explicit "clear filters") clear it directly via `.set(null)`.
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
