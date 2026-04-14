/**
 * Filter application — Wave 7 shim.
 *
 * Pre-Wave-7, this file owned (a) imperative `applyFiltersAndRender` /
 * `applyVerseFilterAndRender` (read state, computed displayed segments,
 * imperatively wrote `state.segDisplayedSegments` and called `renderSegList`),
 * and (b) imperative filter-bar UI (`renderFilterBar` etc.).
 *
 * As of Wave 7:
 *  - FiltersBar.svelte owns the filter-bar UI (subscribes to `activeFilters`).
 *  - SegmentsList.svelte owns row rendering via {#each}, subscribing to
 *    `displayedSegments` (derived from segAllData + selectedChapter +
 *    selectedVerse + activeFilters in lib/stores/segments/filters.ts).
 *
 * This shim remains because edit/save/undo/validation/navigation modules
 * still mutate `state.segAllData.segments` in place and then call
 * `applyFiltersAndRender()` (or `applyVerseFilterAndRender()`) to refresh
 * the visible list. The shim:
 *  1. Resets playback highlight DOM refs (the Wave-5 `renderSegList`
 *     header). Without this, the highlight layer would point to nodes
 *     destroyed by the next {#each} reconciliation.
 *  2. Syncs `state.segActiveFilters` → `activeFilters` store (callers
 *     that mutate state directly need their changes reflected).
 *  3. Notifies `segAllData` subscribers via `update(a => a)` so the
 *     derived `displayedSegments` re-fires and {#each} re-reconciles.
 *
 * `computeSilenceAfter` re-exports from lib/stores/segments/filters.ts
 * (functionally identical — the lib version reads via `get(segAllData)`).
 *
 * Future deletion: when every imperative caller (edit modes, save/undo,
 * validation, navigation) writes through Svelte stores, this shim can go.
 * Until then, it is the bridge.
 */

import { segAllData as segAllDataStore } from '../lib/stores/segments/chapter';
import { activeFilters as activeFiltersStore } from '../lib/stores/segments/filters';
import { state } from './state';

// Re-export shared helpers so existing import sites keep working.
export {
    computeSilenceAfter,
    segDerivedProps,
} from '../lib/stores/segments/filters';
export type { SegDerivedProps } from '../lib/stores/segments/filters';

// ---------------------------------------------------------------------------
// applyFiltersAndRender — Wave 7 shim
// ---------------------------------------------------------------------------

/**
 * Notify Svelte stores that segment data and/or active filters changed so
 * the SegmentsList {#each} re-renders.
 *
 * Imperative callers that mutate `state.segAllData.segments` in place (edit
 * confirm, save flow, undo) call this to publish their change. Callers that
 * mutate `state.segActiveFilters` directly (navigation.ts restore path) get
 * their change synced into the `activeFilters` store here.
 */
export function applyFiltersAndRender(): void {
    // Reset playback highlight DOM refs — the previous {#each} reconciliation
    // may have destroyed the rows these point to. Wave-5 renderSegList did
    // this at line 216-217; the shim preserves the contract.
    state._prevHighlightedRow = null;
    state._prevHighlightedIdx = -1;
    state._currentPlayheadRow = null;
    state._prevPlayheadIdx = -1;

    // Sync state.* (mutated by imperative callers) → store.
    // Spread so the store sees a fresh array reference even when content
    // matches; otherwise `derived` may short-circuit.
    activeFiltersStore.set([...state.segActiveFilters]);

    // Notify segAllData subscribers — the derived `displayedSegments`
    // recomputes from the current (in-place mutated) segments array.
    segAllDataStore.update((a) => a);
}

/** Verse-filter alias preserved for compat (Stage-1 split this for clarity).
 *  Today both paths are identical — the derived store handles verse + filters
 *  together. */
export function applyVerseFilterAndRender(): void {
    applyFiltersAndRender();
}

// ---------------------------------------------------------------------------
// Filter-bar UI helpers — Wave 7 no-op shims
// ---------------------------------------------------------------------------
//
// FiltersBar.svelte renders the filter rows reactively from `$activeFilters`.
// The Stage-1 imperative helpers below would clobber Svelte's #seg-filter-rows
// children; they are now no-ops kept only so navigation.ts and clearAllSegFilters
// continue to compile. Each one writes through the store instead so the
// FiltersBar re-renders.

export function renderFilterBar(): void {
    // No-op: FiltersBar.svelte renders rows from $activeFilters reactively.
    // Sync state → store in case the caller mutated state.segActiveFilters
    // directly (navigation.ts restore path does this).
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
