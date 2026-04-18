/**
 * Edit history panel lifecycle (show/hide).
 *
 * HistoryPanel.svelte owns the panel DOM reactively via the history store.
 * These action functions handle:
 *   - `showHistoryView()` / `hideHistoryView()` → `setHistoryVisible(true/
 *     false)` + `_SEG_NORMAL_IDS` sibling-hide (cross-tab concern kept
 *     imperative per locked Risk #2).
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
} from '../../stores/segments/history';
import { _SEG_NORMAL_IDS } from './constants';
import { stopErrorCardAudio } from './error-card-audio';
import { reloadCurrentReciter } from './reciter-actions';

// ---------------------------------------------------------------------------
// showHistoryView
// ---------------------------------------------------------------------------

export function showHistoryView(): void {
    for (const id of _SEG_NORMAL_IDS) {
        const el = document.getElementById(id);
        if (el) { el.dataset.hiddenByHistory = el.hidden ? '1' : ''; el.hidden = true; }
    }
    const panel = document.getElementById('segments-panel');
    const controls = panel?.querySelector<HTMLElement>('.seg-controls');
    if (controls) { controls.dataset.hiddenByHistory = controls.hidden ? '1' : ''; controls.hidden = true; }
    const shortcuts = panel?.querySelector<HTMLElement>('.shortcuts-guide');
    if (shortcuts) { shortcuts.dataset.hiddenByHistory = shortcuts.hidden ? '1' : ''; shortcuts.hidden = true; }
    clearFilters();
    setSortMode('time');
    setHistoryVisible(true);
}

// ---------------------------------------------------------------------------
// hideHistoryView
// ---------------------------------------------------------------------------

export function hideHistoryView(): void {
    stopErrorCardAudio();
    clearFilters();
    setHistoryVisible(false);
    for (const id of _SEG_NORMAL_IDS) {
        const el = document.getElementById(id);
        if (el) { if (el.dataset.hiddenByHistory !== '1') el.hidden = false; delete el.dataset.hiddenByHistory; }
    }
    const panel = document.getElementById('segments-panel');
    const controls = panel?.querySelector<HTMLElement>('.seg-controls');
    if (controls) { if (controls.dataset.hiddenByHistory !== '1') controls.hidden = false; delete controls.dataset.hiddenByHistory; }
    const shortcuts = panel?.querySelector<HTMLElement>('.shortcuts-guide');
    if (shortcuts) { if (shortcuts.dataset.hiddenByHistory !== '1') shortcuts.hidden = false; delete shortcuts.dataset.hiddenByHistory; }
    if (get(historyDataStale)) { historyDataStale.set(false); void reloadCurrentReciter(); }
}
