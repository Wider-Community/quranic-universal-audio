/**
 * Save flow: preview, confirm, execute save to server.
 */

import { get as storeGet } from 'svelte/store';

import type { HistoryBatch } from '../../../types/domain';
import { dom, state } from '../../segments-state';
import { isDirty } from '../../stores/segments/dirty';
import {
    buildSplitChains,
    buildSplitLineage,
    historyData,
    restoreSplitChains,
    setSplitChains,
    snapshotSplitChains,
} from '../../stores/segments/history';
import {
    clearSavePreviewData,
    hidePreview,
    setSavePreviewData,
    showPreview,
} from '../../stores/segments/save';
import { _SEG_NORMAL_IDS } from './constants';
import { stopErrorCardAudio } from './error-card-audio';
import { reloadCurrentReciter } from './reciter-actions';
import { executeSave } from './save-execute';
import { buildSavePreviewData } from './save-preview';

// Re-export pure utils so callers that used to import from segments/save
// keep one import site.
export { buildSavePreviewData, executeSave };

// ---------------------------------------------------------------------------
// onSegSaveClick -- entry point from Save button
// ---------------------------------------------------------------------------

export async function onSegSaveClick(): Promise<void> {
    if (!isDirty()) return;
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;
    showSavePreview();
}

// ---------------------------------------------------------------------------
// showSavePreview
// ---------------------------------------------------------------------------

export function showSavePreview(): void {
    if (!dom.segSavePreview.hidden) return;
    state._segSavedPreviewState = { scrollTop: dom.segListEl.scrollTop };
    const data = buildSavePreviewData();

    // Snapshot current split-chain state so hideSavePreview can restore it.
    // snapshotSplitChains() returns { chains, chainedOpIds }; map to the
    // legacy SavedChainsSnapshot shape { splitChains, chainedOpIds }.
    const snap = snapshotSplitChains();
    state._segSavedChains = { splitChains: snap.chains, chainedOpIds: snap.chainedOpIds };

    // Rebuild split chains to include pending batches, push to store so
    // SavePreview.svelte (and HistoryPanel) see the augmented chain map.
    const allBatches = [...(storeGet(historyData)?.batches || []), ...(data.batches as HistoryBatch[])];
    const splitLineage = buildSplitLineage(allBatches);
    const built = buildSplitChains(allBatches, splitLineage);
    setSplitChains(built.chains, built.chainedOpIds);

    // Publish preview data to store — SavePreview.svelte renders reactively.
    setSavePreviewData(data);

    for (const id of _SEG_NORMAL_IDS) {
        const el = document.getElementById(id);
        if (el) { el.dataset.hiddenByPreview = el.hidden ? '1' : ''; el.hidden = true; }
    }
    const panel = document.getElementById('segments-panel');
    const controls = panel?.querySelector<HTMLElement>('.seg-controls');
    if (controls) { controls.dataset.hiddenByPreview = controls.hidden ? '1' : ''; controls.hidden = true; }
    const shortcuts = panel?.querySelector<HTMLElement>('.shortcuts-guide');
    if (shortcuts) { shortcuts.dataset.hiddenByPreview = shortcuts.hidden ? '1' : ''; shortcuts.hidden = true; }
    dom.segHistoryView.hidden = true;

    dom.segSavePreview.hidden = false;
    showPreview(); // notify $savePreviewVisible store (SavePreview.svelte hidden binding)
}

// ---------------------------------------------------------------------------
// hideSavePreview
// ---------------------------------------------------------------------------

export function hideSavePreview(restoreScroll = true): void {
    stopErrorCardAudio();
    dom.segSavePreview.hidden = true;
    hidePreview(); // notify $savePreviewVisible store (SavePreview.svelte hidden binding)
    clearSavePreviewData(); // clear store — SavePreview.svelte empties reactively

    if (state._segSavedChains) {
        // Restore split chains to their pre-preview state via the store.
        // Map legacy { splitChains, chainedOpIds } to store's { chains, chainedOpIds }.
        restoreSplitChains({ chains: state._segSavedChains.splitChains, chainedOpIds: state._segSavedChains.chainedOpIds });
        state._segSavedChains = null;
    }

    for (const id of _SEG_NORMAL_IDS) {
        const el = document.getElementById(id);
        if (el) { if (el.dataset.hiddenByPreview !== '1') el.hidden = false; delete el.dataset.hiddenByPreview; }
    }
    const panel = document.getElementById('segments-panel');
    const controls = panel?.querySelector<HTMLElement>('.seg-controls');
    if (controls) { if (controls.dataset.hiddenByPreview !== '1') controls.hidden = false; delete controls.dataset.hiddenByPreview; }
    const shortcuts = panel?.querySelector<HTMLElement>('.shortcuts-guide');
    if (shortcuts) { if (shortcuts.dataset.hiddenByPreview !== '1') shortcuts.hidden = false; delete shortcuts.dataset.hiddenByPreview; }

    if (state._segDataStale) {
        state._segDataStale = false;
        state._segSavedPreviewState = null;
        void reloadCurrentReciter();
    } else if (restoreScroll && state._segSavedPreviewState) {
        const saved = state._segSavedPreviewState;
        state._segSavedPreviewState = null;
        requestAnimationFrame(() => { dom.segListEl.scrollTop = saved.scrollTop; });
    }
}

// ---------------------------------------------------------------------------
// confirmSaveFromPreview
// ---------------------------------------------------------------------------

export async function confirmSaveFromPreview(): Promise<void> {
    hideSavePreview(false);
    await executeSave();
}
