import { get as storeGet } from 'svelte/store';

import { fetchJson, fetchJsonOrNull } from '../../../../lib/api';
import type {
    SegEditHistoryResponse,
    SegUndoBatchResponse,
    SegUndoOpsResponse,
} from '../../../../lib/types/api';
import type { EditOp, HistoryBatch } from '../../../../lib/types/domain';
import { surahOptionText } from '../../../../lib/utils/surah-info';
import { segAllData, selectedReciter } from '../../stores/chapter';
import {
    getChapterOps,
    isDirty,
    recomputeDirtyEntryFromOps,
    setChapterOps,
} from '../../stores/dirty';
import { pendingChainTarget } from '../../stores/edit';
import {
    buildEditChains,
    historyData,
    historyDataStale,
    setEditChains,
    type EditChain,
} from '../../stores/history';
import { setSavePreviewData } from '../../stores/save';
import { applyInversePatchToSegments } from '../../domain/inverse-patch';
import { renderEditHistoryPanel } from '../history/render';
import { buildSavePreviewData, hideSavePreview } from './actions';

// ---------------------------------------------------------------------------
// _afterUndoSuccess -- shared post-undo refresh
// ---------------------------------------------------------------------------

export async function _afterUndoSuccess(reciter: string, opsReversed: number): Promise<void> {
    pendingChainTarget.set(null);

    try {
        const hist = await fetchJsonOrNull<SegEditHistoryResponse>(
            `/api/seg/edit-history/${reciter}`,
        );
        if (hist) {
            renderEditHistoryPanel(hist);
        }
    } catch (_) { /* non-critical */ }
    historyDataStale.set(true);
    fetchJson(`/api/seg/trigger-validation/${reciter}`, { method: 'POST' }).catch(() => {});
}

// ---------------------------------------------------------------------------
// onBatchUndoClick
// ---------------------------------------------------------------------------

export async function onBatchUndoClick(batchId: string, chapter: number | null, btn: HTMLButtonElement): Promise<void> {
    const reciter = storeGet(selectedReciter);
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
    const reciter = storeGet(selectedReciter);
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

export function _getChainBatchIds(chain: EditChain): string[] {
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
    const reciter = storeGet(selectedReciter);
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
    if (failed) {
        btn.disabled = false;
        btn.textContent = 'Undo';
    }
}

// ---------------------------------------------------------------------------
// onPendingOpsDiscard -- atomic per-card discard of unsaved ops
// ---------------------------------------------------------------------------

/**
 * Atomically revert a specific subset of unsaved ops for a chapter without
 * touching the rest of that chapter's pending edits.
 *
 * Each unsaved op carries a forward `patch` (attached at finalize time —
 * see `finalizeEdit`). We invert those patches in reverse op-log order
 * against `segAllData.segments`, drop the discarded ops from `_opLog`,
 * and recompute the chapter's dirty entry from the kept ops. If no kept
 * ops remain, the chapter exits dirty state and the save preview hides.
 *
 * Discard is client-only — server history is unchanged, so do NOT set
 * `historyDataStale`. Doing so caused an earlier bug (commit `e73a46d`)
 * where confirming the save afterwards triggered a fire-and-forget
 * `reloadCurrentReciter()` that raced `executeSave()` and wiped the
 * remaining dirty chapters' ops.
 *
 * `groupRelatedOps` (utils/history/items.ts) ensures one card's ops form
 * a uid-connected component with no overlap into other cards' uid sets,
 * so this revert cannot bleed into other cards' segments.
 */
export function onPendingOpsDiscard(
    chapter: number,
    opIds: string[],
    btn: HTMLButtonElement,
): void {
    void btn;
    if (opIds.length === 0) return;
    const chLabel = chapter != null ? ` for ${surahOptionText(chapter)}` : '';
    const noun = opIds.length === 1 ? 'edit' : 'edits';
    if (!confirm(`Discard ${opIds.length} ${noun}${chLabel}?`)) return;

    pendingChainTarget.set(null);

    const opIdSet = new Set(opIds);
    const all = getChapterOps(chapter);
    const toRevert: EditOp[] = [];
    const toKeep: EditOp[] = [];
    for (const op of all) {
        if (opIdSet.has(op.op_id)) toRevert.push(op);
        else toKeep.push(op);
    }

    // Reverse-apply each discarded op's forward patch to segAllData. Walk
    // in REVERSE op-log order so chained ops (split → edit-ref) invert
    // in the correct sequence: undo edit-ref first, then split.
    if (toRevert.length > 0) {
        segAllData.update((d) => {
            if (!d) return d;
            let segs = d.segments;
            for (let i = toRevert.length - 1; i >= 0; i--) {
                const op = toRevert[i]!;
                if (op.patch) {
                    segs = applyInversePatchToSegments(segs, op.patch);
                } else {
                    console.warn(
                        '[discard] op missing patch — cannot revert in-place',
                        op.op_id,
                        op.op_type,
                    );
                }
            }
            return { ...d, segments: segs };
        });
    }

    setChapterOps(chapter, toKeep);
    recomputeDirtyEntryFromOps(chapter, toKeep);

    if (!isDirty()) {
        hideSavePreview();
        return;
    }
    const data = buildSavePreviewData();
    const allBatches = [...(storeGet(historyData)?.batches || []), ...(data.batches as HistoryBatch[])];
    const built = buildEditChains(allBatches);
    setEditChains(built.chains, built.chainedOpIds);
    setSavePreviewData(data);
}
