/**
 * Edit history panel lifecycle (show/hide).
 *
 * HistoryPanel.svelte owns the panel DOM reactively via the history store.
 * `SegmentsTab.svelte` hides the normal-content block reactively when
 * `$historyVisible` is true, so these actions only toggle the store.
 *
 * `renderEditHistoryPanel` lives in `history-render.ts` to avoid a cycle
 * with `reciter-actions.ts`.
 */

import { get } from 'svelte/store';

import {
    clearFilters,
    historyDataStale,
    setHistoryVisible,
    setSortMode,
} from '../../stores/history';
import { reloadCurrentReciter } from '../data/reciter-actions';

// ---------------------------------------------------------------------------
// showHistoryView
// ---------------------------------------------------------------------------

export function showHistoryView(): void {
    clearFilters();
    setSortMode('time');
    setHistoryVisible(true);
}

// ---------------------------------------------------------------------------
// hideHistoryView
// ---------------------------------------------------------------------------

export function hideHistoryView(): void {
    clearFilters();
    setHistoryVisible(false);
    if (get(historyDataStale)) {
        historyDataStale.set(false);
        void reloadCurrentReciter();
    }
}
