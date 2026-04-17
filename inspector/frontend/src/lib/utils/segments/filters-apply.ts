/**
 * Filter application bridge between imperative mutations and Svelte stores.
 *
 * FiltersBar.svelte owns the filter-bar UI and SegmentsList.svelte owns row
 * rendering. Imperative modules (edit/save/undo/validation/navigation) still
 * mutate `state.segAllData.segments` in place and then call
 * `applyFiltersAndRender()` or `applyVerseFilterAndRender()` to republish
 * their change:
 *  1. Reset playback highlight DOM refs so the highlight layer does not
 *     point to nodes destroyed by the next {#each} reconciliation.
 *  2. Sync `state.segActiveFilters` → `activeFilters` store (callers that
 *     mutate state directly need their changes reflected).
 *  3. Notify `segAllData` subscribers via `update(a => a)` so the derived
 *     `displayedSegments` re-fires and {#each} re-reconciles.
 */

import { state } from '../../segments-state';
import { segAllData as segAllDataStore } from '../../stores/segments/chapter';
import { activeFilters as activeFiltersStore } from '../../stores/segments/filters';

// Re-export shared helpers so existing import sites keep working.
export {
    computeSilenceAfter,
    segDerivedProps,
} from '../../stores/segments/filters';
export type { SegDerivedProps } from '../../stores/segments/filters';

/**
 * Notify Svelte stores that segment data and/or active filters changed so
 * the SegmentsList {#each} re-renders.
 */
export function applyFiltersAndRender(): void {
    state._prevHighlightedRow = null;
    state._prevHighlightedIdx = -1;
    state._currentPlayheadRow = null;
    state._prevPlayheadIdx = -1;

    // Spread so the store sees a fresh array reference even when content
    // matches; otherwise `derived` may short-circuit.
    activeFiltersStore.set([...state.segActiveFilters]);

    // The derived `displayedSegments` recomputes from the current (in-place
    // mutated) segments array.
    segAllDataStore.update((a) => a);
}

/** Verse-filter alias preserved for compat — today both paths are identical. */
export function applyVerseFilterAndRender(): void {
    applyFiltersAndRender();
}

// ---------------------------------------------------------------------------
// Filter-bar UI helpers — no-op shims that publish through the store
// ---------------------------------------------------------------------------
//
// FiltersBar.svelte renders the filter rows reactively from `$activeFilters`.
// Legacy imperative helpers below are kept so navigation.ts + clearAllSegFilters
// continue to compile. Each one writes through the store so FiltersBar re-renders.

export function renderFilterBar(): void {
    // Sync state → store in case the caller mutated state.segActiveFilters directly.
    activeFiltersStore.set([...state.segActiveFilters]);
}

export function updateFilterBarControls(): void {
    // No-op: FiltersBar.svelte derives count + clear-button visibility from
    // $activeFilters reactively.
}

export function addSegFilterCondition(): void {
    activeFiltersStore.update((list) => [
        ...list,
        { field: 'duration_s', op: '>', value: null },
    ]);
}

export function clearAllSegFilters(): void {
    state.segActiveFilters = [];
    state._segSavedFilterView = null;
    activeFiltersStore.set([]);
    applyFiltersAndRender();
}
