/**
 * Save flow: preview, confirm, execute save to server.
 */

import { get as storeGet } from 'svelte/store';

import type { HistoryBatch } from '../../../types/domain';
import { selectedReciter } from '../../stores/segments/chapter';
import { isDirty } from '../../stores/segments/dirty';
import {
    buildSplitChains,
    buildSplitLineage,
    historyData,
    historyDataStale,
    restoreSplitChains,
    setHistoryVisible,
    setSplitChains,
    snapshotSplitChains,
} from '../../stores/segments/history';
import { segListElement } from '../../stores/segments/playback';
import {
    clearSavePreviewData,
    hidePreview,
    savedChains,
    savedPreviewScroll,
    savePreviewVisible,
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
    const reciter = storeGet(selectedReciter);
    if (!reciter) return;
    showSavePreview();
}

// ---------------------------------------------------------------------------
// showSavePreview
// ---------------------------------------------------------------------------

export function showSavePreview(): void {
    if (storeGet(savePreviewVisible)) return;
    const listEl = storeGet(segListElement);
    savedPreviewScroll.set(listEl?.scrollTop ?? 0);
    const data = buildSavePreviewData();

    // Snapshot current split-chain state so hideSavePreview can restore it.
    // snapshotSplitChains() returns { chains, chainedOpIds }; map to the
    // SavedChainsSnapshot shape { splitChains, chainedOpIds }.
    const snap = snapshotSplitChains();
    savedChains.set({ splitChains: snap.chains, chainedOpIds: snap.chainedOpIds });

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
    setHistoryVisible(false);

    showPreview();
}

// ---------------------------------------------------------------------------
// hideSavePreview
// ---------------------------------------------------------------------------

export function hideSavePreview(restoreScroll = true): void {
    stopErrorCardAudio();
    hidePreview();
    clearSavePreviewData();

    const snap = storeGet(savedChains);
    if (snap) {
        restoreSplitChains({ chains: snap.splitChains, chainedOpIds: snap.chainedOpIds });
        savedChains.set(null);
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

    if (storeGet(historyDataStale)) {
        historyDataStale.set(false);
        savedPreviewScroll.set(null);
        void reloadCurrentReciter();
    } else if (restoreScroll) {
        const scrollTop = storeGet(savedPreviewScroll);
        if (scrollTop !== null) {
            savedPreviewScroll.set(null);
            requestAnimationFrame(() => {
                const listEl = storeGet(segListElement);
                if (listEl) listEl.scrollTop = scrollTop;
            });
        }
    }
}

// ---------------------------------------------------------------------------
// confirmSaveFromPreview
// ---------------------------------------------------------------------------

export async function confirmSaveFromPreview(): Promise<void> {
    hideSavePreview(false);
    await executeSave();
}
