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
import { pendingScrollTop } from '../../stores/segments/navigation';
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
