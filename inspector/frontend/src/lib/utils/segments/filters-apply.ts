/**
 * Filter application helpers: republish segment mutations to Svelte stores.
 *
 * FiltersBar.svelte owns the filter-bar UI and SegmentsList.svelte owns row
 * rendering. Edit/save/undo/validation/navigation modules mutate
 * `segAllData.segments` in place and then call `applyFiltersAndRender()` or
 * `applyVerseFilterAndRender()` to republish their change:
 *  1. Reset playback highlight DOM refs so the highlight layer does not
 *     point to nodes destroyed by the next {#each} reconciliation.
 *  2. Nudge `activeFilters` store (`update(a => [...a])`) so subscribers see
 *     the new data even when filter list is unchanged.
 *  3. Notify `segAllData` subscribers via `update(a => a)` so the derived
 *     `displayedSegments` re-fires and {#each} re-reconciles.
 */

import { segAllData } from '../../stores/segments/chapter';
import { activeFilters } from '../../stores/segments/filters';
import { savedFilterView } from '../../stores/segments/navigation';
import { resetHighlightRefs } from './playback';

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
    resetHighlightRefs();

    // Spread so subscribers see a fresh array reference even when the
    // content matches; otherwise `derived` may short-circuit.
    activeFilters.update((list) => [...list]);

    // The derived `displayedSegments` recomputes from the current (in-place
    // mutated) segments array.
    segAllData.update((a) => a);
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
    // Nudge subscribers so the filter bar re-renders.
    activeFilters.update((list) => [...list]);
}

export function updateFilterBarControls(): void {
    // No-op: FiltersBar.svelte derives count + clear-button visibility from
    // $activeFilters reactively.
}

export function addSegFilterCondition(): void {
    activeFilters.update((list) => [
        ...list,
        { field: 'duration_s', op: '>', value: null },
    ]);
}

export function clearAllSegFilters(): void {
    activeFilters.set([]);
    savedFilterView.set(null);
    applyFiltersAndRender();
}
