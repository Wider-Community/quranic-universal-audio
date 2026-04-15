/**
 * Edit history panel lifecycle (show/hide) and data loading.
 *
 * Wave 10: HistoryPanel.svelte owns the panel DOM reactively. This module
 * now bridges to the history store:
 *   - `renderEditHistoryPanel(data)` → `setHistoryData(data)` (rebuilds
 *     split chains in-store) + toggles the external history button.
 *   - `showHistoryView()` / `hideHistoryView()` → `setHistoryVisible(true/
 *     false)` + the `_SEG_NORMAL_IDS` sibling-hide (cross-tab concern that
 *     stays imperative per locked Risk #2).
 *
 * Store writes cascade to HistoryPanel (summary stats, filter bar, batches)
 * and HistoryArrows (afterUpdate re-measure); no imperative innerHTML is
 * issued into the Svelte-owned subtree.
 */

import {
    clearFilters,
    setHistoryData,
    setHistoryVisible,
    setSortMode,
} from '../../lib/stores/segments/history';
import type { SegEditHistoryResponse } from '../../types/api';
import { _SEG_NORMAL_IDS } from '../constants';
import { dom, state } from '../state';
import { stopErrorCardAudio } from '../validation/error-card-audio';

// ---------------------------------------------------------------------------
// Break history/index ↔ data circular dependency (S2-B06 / P4).
// `onSegReciterChange` is registered by segments/index.ts after both modules load.
// ---------------------------------------------------------------------------

let _onSegReciterChangeFn: (() => void) | null = null;
export function registerOnSegReciterChange(fn: () => void): void { _onSegReciterChangeFn = fn; }

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
    if (state._segDataStale) { state._segDataStale = false; _onSegReciterChangeFn?.(); }
}

// ---------------------------------------------------------------------------
// renderEditHistoryPanel -- bridge to the history store.
// ---------------------------------------------------------------------------

export function renderEditHistoryPanel(data: SegEditHistoryResponse | null | undefined): void {
    if (!data || !data.batches || data.batches.length === 0) {
        dom.segHistoryBtn.hidden = true;
        setHistoryData(null);
        return;
    }
    dom.segHistoryBtn.hidden = false;
    setHistoryData(data);
}

// Split-chain/lineage helpers moved to lib/stores/segments/history.ts
// (Wave 10). Callers previously using `_buildSplitLineage` /
// `_buildSplitChains` should import `buildSplitLineage` / `buildSplitChains`
// from the store module directly.
