/**
 * Save flow: preview, confirm, execute save to server.
 */

import { get as storeGet } from 'svelte/store';

import type { HistoryBatch } from '../../../../lib/types/domain';
import { selectedReciter } from '../../stores/chapter';
import { isDirty } from '../../stores/dirty';
import {
    buildEditChains,
    historyData,
    historyDataStale,
    restoreEditChains,
    setHistoryVisible,
    setEditChains,
    snapshotEditChains,
} from '../../stores/history';
import { pendingScrollTop } from '../../stores/navigation';
import { segListElement } from '../../stores/playback';
import {
    clearSavePreviewData,
    hidePreview,
    savedChains,
    savedPreviewScroll,
    savePreviewVisible,
    setSavePreviewData,
    showPreview,
} from '../../stores/save';
import { reloadCurrentReciter } from '../data/reciter-actions';
import { executeSave } from './execute';
import { buildSavePreviewData } from './preview';
import { refreshValidation } from '../validation/refresh';

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
    // snapshotEditChains() returns { chains, chainedOpIds }; map to the
    // SavedChainsSnapshot shape { editChains, chainedOpIds }.
    const snap = snapshotEditChains();
    savedChains.set({ editChains: snap.chains, chainedOpIds: snap.chainedOpIds });

    // Rebuild edit chains to include pending batches, push to store so
    // SavePreview.svelte (and HistoryPanel) see the augmented chain map.
    const allBatches = [...(storeGet(historyData)?.batches || []), ...(data.batches as HistoryBatch[])];
    const built = buildEditChains(allBatches);
    setEditChains(built.chains, built.chainedOpIds);

    // Publish preview data to store — SavePreview.svelte renders reactively.
    setSavePreviewData(data);

    setHistoryVisible(false);

    showPreview();
}

// ---------------------------------------------------------------------------
// hideSavePreview
// ---------------------------------------------------------------------------

export function hideSavePreview(restoreScroll = true): void {
    hidePreview();
    clearSavePreviewData();
    void refreshValidation();

    const snap = storeGet(savedChains);
    if (snap) {
        restoreEditChains({ chains: snap.editChains, chainedOpIds: snap.chainedOpIds });
        savedChains.set(null);
    }

    if (storeGet(historyDataStale)) {
        historyDataStale.set(false);
        savedPreviewScroll.set(null);
        void reloadCurrentReciter();
    } else if (restoreScroll) {
        const scrollTop = storeGet(savedPreviewScroll);
        if (scrollTop !== null) {
            savedPreviewScroll.set(null);
            // SegmentsList.afterUpdate consumes pendingScrollTop after the
            // {#each} reconciles, so the scroll lands once the remounted
            // list has its rows in place.
            pendingScrollTop.set(scrollTop);
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
