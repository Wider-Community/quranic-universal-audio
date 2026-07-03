import { get as storeGet } from 'svelte/store';

import { fetchJson } from '../../../../lib/api';
import * as m from '../../../../lib/paraglide/messages';
import type { SegUndoResponse as SegUndoBatchResponse, SegUndoResponse as SegUndoOpsResponse } from '../../../../lib/types/generated/schemas';
import type { EditOp, HistoryBatch } from '../../../../lib/types/view-models';
import { surahOptionText } from '../../../../lib/utils/surah-info';
import { applyInversePatchToSegments } from '../../domain/inverse-patch';
import { segAllData, selectedReciter } from '../../stores/chapter';
import {
    getChapterOps,
    isDirty,
    recomputeDirtyEntryFromOps,
    setChapterOps,
} from '../../stores/dirty';
import { pendingChainTargets, pendingWaslConfirm } from '../../stores/edit';
import {
    buildEditChains,
    type EditChain,
    historyData,
    historyDataStale,
    setEditChains,
} from '../../stores/history';
import { setSavePreviewData } from '../../stores/save';
import { clearUndoing, markUndoing } from '../../stores/undo-pending';
import { reloadSegAll } from '../data/reciter-actions';
import { refreshValidation } from '../validation/refresh';
import { buildSavePreviewData, hideSavePreview } from './actions';

// ---------------------------------------------------------------------------
// _afterUndoSuccess -- shared post-undo refresh
// ---------------------------------------------------------------------------

export async function _afterUndoSuccess(reciter: string, _opsReversed: number): Promise<void> {
    pendingChainTargets.set([]);
    pendingWaslConfirm.set(new Set());

    // Mark history stale so the next History-panel open refetches. We
    // intentionally do NOT eagerly refetch /api/seg/edit-history here —
    // the panel is lazy-fetched on open, and validation/reloadSegAll below
    // already cover everything the rest of the UI needs.
    historyDataStale.set(true);
    // Undo invalidates validation + seg data server-side. Validation counters
    // depend on segAllData.segments (filterStaleIssues uses liveUids) — without
    // reloading /seg/all the counts can lag behind the validation response.
    // The validate response also carries the refreshed split_group_index.
    // Stats are NOT refreshed here: StatsPanel lazy-fetches on accordion open.
    void refreshValidation();
    void reloadSegAll();
    void reciter; // signature kept for caller compatibility
}

// ---------------------------------------------------------------------------
// onBatchUndoClick
// ---------------------------------------------------------------------------

export async function onBatchUndoClick(batchId: string, chapter: number | null): Promise<void> {
    const reciter = storeGet(selectedReciter);
    if (!reciter) return;
    const chLabel = chapter != null ? ` for ${surahOptionText(chapter)}` : '';
    if (!confirm(m.segments_undo_batch_confirm({ ch_label: chLabel }))) return;

    markUndoing(batchId);
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
            alert(m.segments_undo_generic_failed_alert({ error: result.error ?? '' }));
        }
    } catch (e) {
        console.error('Undo batch failed:', e);
        alert(m.segments_undo_console_error_alert());
    } finally {
        clearUndoing(batchId);
    }
}

// ---------------------------------------------------------------------------
// onOpUndoClick
// ---------------------------------------------------------------------------

export async function onOpUndoClick(batchId: string, opIds: string[]): Promise<void> {
    const reciter = storeGet(selectedReciter);
    if (!reciter) return;
    if (!confirm(m.segments_undo_op_confirm())) return;

    const opKey = `${batchId}:${opIds.join(',')}`;
    markUndoing(opKey);
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
            alert(m.segments_undo_generic_failed_alert({ error: result.error ?? '' }));
        }
    } catch (e) {
        console.error('Undo op failed:', e);
        alert(m.segments_undo_console_error_alert());
    } finally {
        clearUndoing(opKey);
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

export async function onChainUndoClick(batchIds: string[], chapter: number | null): Promise<void> {
    const reciter = storeGet(selectedReciter);
    if (!reciter) return;
    const chLabel = chapter != null ? ` for ${surahOptionText(chapter)}` : '';
    if (!confirm(m.segments_undo_chain_confirm({ count: batchIds.length, ch_label: chLabel }))) return;

    const chainKey = `chain:${batchIds.join(',')}`;
    markUndoing(chainKey);
    let totalReversed = 0;
    let failed = false;
    try {
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
                    alert(m.segments_undo_chain_batch_failed_alert({
                        n: batchIds.indexOf(batchId) + 1,
                        total: batchIds.length,
                        error: result.error ?? '',
                    }));
                    failed = true;
                    break;
                }
            } catch (e) {
                console.error('Chain undo failed:', e);
                alert(m.segments_undo_console_error_alert());
                failed = true;
                break;
            }
        }

        // Only refresh on success. Calling _afterUndoSuccess on a partial
        // failure rebuilds the history panel against fresh server state
        // mid-chain \u2014 visually "consuming" the failed undo, plus setting
        // historyDataStale=true which then triggers reloadCurrentReciter()
        // on the next hideSavePreview and can wipe still-pending ops.
        if (!failed) {
            await _afterUndoSuccess(reciter, totalReversed);
        }
    } finally {
        clearUndoing(chainKey);
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
    if (!confirm(m.segments_discard_confirm({ count: opIds.length, ch_label: chLabel }))) return;

    pendingChainTargets.set([]);
    pendingWaslConfirm.set(new Set());

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
