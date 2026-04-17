import { get as storeGet } from 'svelte/store';

import { dom, state } from '../../../segments/state';
import type {
    SegEditHistoryResponse,
    SegUndoBatchResponse,
    SegUndoOpsResponse,
} from '../../../types/api';
import type { HistoryBatch } from '../../../types/domain';
import { fetchJson, fetchJsonOrNull } from '../../api';
import {
    deleteDirtyEntry,
    deleteOpLogEntry,
    isDirty,
} from '../../stores/segments/dirty';
import {
    buildSplitChains,
    buildSplitLineage,
    historyData,
    setHistoryData,
    setSplitChains,
    type SplitChain,
} from '../../stores/segments/history';
import { setSavePreviewData } from '../../stores/segments/save';
import { surahOptionText } from '../surah-info';
import { renderEditHistoryPanel } from './history-render';
import { buildSavePreviewData, hideSavePreview } from './save-actions';

// ---------------------------------------------------------------------------
// _afterUndoSuccess -- shared post-undo refresh
// ---------------------------------------------------------------------------

export async function _afterUndoSuccess(reciter: string, opsReversed: number): Promise<void> {
    state._splitChainUid = null;
    state._splitChainWrapper = null;
    state._splitChainCategory = null;

    try {
        const hist = await fetchJsonOrNull<SegEditHistoryResponse>(
            `/api/seg/edit-history/${reciter}`,
        );
        if (hist) {
            renderEditHistoryPanel(hist);
        }
    } catch (_) { /* non-critical */ }
    state._segDataStale = true;
    fetchJson(`/api/seg/trigger-validation/${reciter}`, { method: 'POST' }).catch(() => {});
    dom.segPlayStatus.textContent = `Undo successful \u2014 ${opsReversed} op${opsReversed !== 1 ? 's' : ''} reversed`;
}

// ---------------------------------------------------------------------------
// onBatchUndoClick
// ---------------------------------------------------------------------------

export async function onBatchUndoClick(batchId: string, chapter: number | null, btn: HTMLButtonElement): Promise<void> {
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;
    const chLabel = chapter != null ? ` for ${surahOptionText(chapter)}` : '';
    if (!confirm(`Undo this save${chLabel}? The operations will be reversed.`)) return;

    btn.disabled = true;
    btn.textContent = 'Undoing...';

    try {
        const result = await fetchJson<SegUndoBatchResponse & { error?: string; operations_reversed?: number }>(
            `/api/seg/undo-batch/${reciter}`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ batch_id: batchId }),
            },
        );
        if (result.ok) {
            await _afterUndoSuccess(reciter, result.operations_reversed ?? 0);
        } else {
            alert(`Undo failed: ${result.error}`);
            btn.disabled = false;
            btn.textContent = 'Undo';
        }
    } catch (e) {
        console.error('Undo batch failed:', e);
        alert('Undo failed \u2014 see console for details');
        btn.disabled = false;
        btn.textContent = 'Undo';
    }
}

// ---------------------------------------------------------------------------
// onOpUndoClick
// ---------------------------------------------------------------------------

export async function onOpUndoClick(batchId: string, opIds: string[], btn: HTMLButtonElement): Promise<void> {
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;
    if (!confirm('Undo this operation?')) return;

    btn.disabled = true;
    btn.textContent = 'Undoing...';

    try {
        const result = await fetchJson<SegUndoOpsResponse & { error?: string; operations_reversed?: number }>(
            `/api/seg/undo-ops/${reciter}`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ batch_id: batchId, op_ids: opIds }),
            },
        );
        if (result.ok) {
            await _afterUndoSuccess(reciter, result.operations_reversed ?? 0);
        } else {
            alert(`Undo failed: ${result.error}`);
            btn.disabled = false;
            btn.textContent = 'Undo';
        }
    } catch (e) {
        console.error('Undo op failed:', e);
        alert('Undo failed \u2014 see console for details');
        btn.disabled = false;
        btn.textContent = 'Undo';
    }
}

// ---------------------------------------------------------------------------
// _getChainBatchIds
// ---------------------------------------------------------------------------

export function _getChainBatchIds(chain: SplitChain): string[] {
    const seen = new Set<string>();
    const ids: string[] = [];
    for (let i = chain.ops.length - 1; i >= 0; i--) {
        const batchId = chain.ops[i]?.batch?.batch_id;
        if (batchId && !seen.has(batchId)) {
            seen.add(batchId);
            ids.push(batchId);
        }
    }
    return ids;
}

// ---------------------------------------------------------------------------
// onChainUndoClick
// ---------------------------------------------------------------------------

export async function onChainUndoClick(batchIds: string[], chapter: number | null, btn: HTMLButtonElement): Promise<void> {
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;
    const chLabel = chapter != null ? ` for ${surahOptionText(chapter)}` : '';
    if (!confirm(`Undo this entire split chain${chLabel}? ${batchIds.length} save(s) will be reversed in order.`)) return;

    btn.disabled = true;
    btn.textContent = 'Undoing...';

    let totalReversed = 0;
    let failed = false;
    for (const batchId of batchIds) {
        try {
            const result = await fetchJson<SegUndoBatchResponse & { error?: string; operations_reversed?: number }>(
                `/api/seg/undo-batch/${reciter}`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ batch_id: batchId }),
                },
            );
            if (result.ok) {
                totalReversed += result.operations_reversed || 0;
            } else {
                alert(`Undo failed on batch ${batchIds.indexOf(batchId) + 1}/${batchIds.length}: ${result.error}`);
                failed = true;
                break;
            }
        } catch (e) {
            console.error('Chain undo failed:', e);
            alert('Undo failed \u2014 see console for details');
            failed = true;
            break;
        }
    }

    await _afterUndoSuccess(reciter, totalReversed);
    if (!failed) {
        dom.segPlayStatus.textContent = `Undo successful \u2014 ${totalReversed} op${totalReversed !== 1 ? 's' : ''} reversed across ${batchIds.length} save(s)`;
    } else {
        btn.disabled = false;
        btn.textContent = 'Undo';
    }
}

// ---------------------------------------------------------------------------
// onPendingBatchDiscard -- discard unsaved edits for a chapter
// ---------------------------------------------------------------------------

export function onPendingBatchDiscard(chapter: number, btn: HTMLButtonElement): void {
    void btn;
    const chLabel = chapter != null ? ` for ${surahOptionText(chapter)}` : '';
    if (!confirm(`Discard pending edits${chLabel}?`)) return;

    state._splitChainUid = null;
    state._splitChainWrapper = null;
    state._splitChainCategory = null;

    // Ph4a: use dirty store helpers (number keys only — fixes B01).
    deleteDirtyEntry(chapter);
    deleteOpLogEntry(chapter);

    state._segDataStale = true;
    dom.segSaveBtn.disabled = !isDirty();

    if (!isDirty()) {
        hideSavePreview();
        return;
    }
    const data = buildSavePreviewData();
    const allBatches = [...(storeGet(historyData)?.batches || []), ...(data.batches as HistoryBatch[])];
    const splitLineage = buildSplitLineage(allBatches);
    const built = buildSplitChains(allBatches, splitLineage);
    setSplitChains(built.chains, built.chainedOpIds);
    setHistoryData(storeGet(historyData));
    setSavePreviewData(data);
}
