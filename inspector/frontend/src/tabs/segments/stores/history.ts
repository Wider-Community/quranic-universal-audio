/**
 * Segments tab — edit-history view store.
 *
 * Owns writables (visibility, raw response, filter sets, sort mode),
 * store actions, and the derived `flatItems` store.
 * Pure helpers live in:
 *   lib/utils/segments/history-chains.ts  — split-chain building
 *   lib/utils/segments/history-items.ts   — flattening, grouping, display items
 */

import { derived, get, writable } from 'svelte/store';

import type { SegEditHistoryResponse } from '../../../lib/types/api';
import type { EditChain } from '../types/segments';
import {
    buildEditChains,
} from '../utils/history/chains';
import { flattenBatchesToItems } from '../utils/history/items';

// Re-export chain helpers so existing consumers keep one import site.
export {
    buildEditChains,
    computeChainLeafSnaps,
    getChainBatchIds,
    snapToSeg,
    type BuildChainsResult,
    type EditChain as SplitChain,
    type EditChainOp as SplitChainOp,
    type EditChain,
    type EditChainOp,
} from '../utils/history/chains';

// Re-export item helpers so existing consumers keep one import site.
export {
    buildDisplayItems,
    chainHasWaslAnnotation,
    computeFilteredSummary,
    countVersesFromBatches,
    countVersesFromItems,
    flattenBatchesToItems,
    formatHistDate,
    groupRelatedOps,
    histItemChapter,
    histItemTimeStart,
    itemHasWaslAnnotation,
    itemMatchesCatFilter,
    itemMatchesOpFilter,
    SHORT_LABELS,
    versesFromRef,
    type DisplayEntry,
    type FilteredItemSummary,
    type HistorySnapshot,
    type OpFlatItem,
} from '../utils/history/items';

// ---------------------------------------------------------------------------
// Stores
// ---------------------------------------------------------------------------

/** Raw edit-history response from `/api/seg/edit-history/<reciter>`. */
export const historyData = writable<SegEditHistoryResponse | null>(null);

/** Loading state for the lazy/background edit-history fetch. */
export const historyLoadState = writable<'idle' | 'loading' | 'loaded' | 'empty' | 'error'>('idle');

/** Map of edit-chain id (root op_id) → chain descriptor. */
export const editChains = writable<Map<string, EditChain> | null>(null);

/** Set of op_ids absorbed into split chains (so they hide from flat items). */
export const chainedOpIds = writable<Set<string> | null>(null);

/** Active op-type filter pills (e.g. {"split_segment"}). */
export const filterOpTypes = writable<Set<string>>(new Set());

/** Active error-category filter pills (e.g. {"low_confidence"}). */
export const filterErrCats = writable<Set<string>>(new Set());

/** Single boolean filter — when true, restrict the display to entries whose
 *  ops carry at least one targets_after / snapshots.after snapshot with
 *  ``is_wasl !== undefined`` (either committed wasl or committed waqf). Gives
 *  the user a one-click way to find rows where they made boundary decisions
 *  without having to scan the saved batches list. */
export const filterHasWasl = writable<boolean>(false);

/** Sort order: by edit time (newest first) or by Quran chapter:verse. */
export const sortMode = writable<'time' | 'quran'>('time');

/** Whether the edit-history view is currently shown. */
export const historyVisible = writable<boolean>(false);

/** True after an undo (in-view) so hideHistoryView can trigger a full reciter
 *  reload. Raw response data remains in `historyData` until the reload. */
export const historyDataStale = writable<boolean>(false);

/** Cached flat items list (rebuilt when historyData / chainedOpIds change). */
export const flatItems = derived(
    [historyData, chainedOpIds],
    ([$data, $chained]) => {
        if (!$data || !$data.batches || $data.batches.length === 0) return [];
        return flattenBatchesToItems($data.batches, $chained ?? new Set());
    },
);

// ---------------------------------------------------------------------------
// Store API
// ---------------------------------------------------------------------------

/**
 * Set the raw history data and rebuild derived split chains.
 *
 * Pass `null` to clear (e.g. on reciter change).
 */
export function setHistoryData(data: SegEditHistoryResponse | null): void {
    if (data && data.batches) {
        data = {
            ...data,
            batches: data.batches.filter(b => b.batch_type !== 'pad_migration'),
        };
        for (const batch of data.batches) {
            const isStripSpecials = batch.batch_type === 'strip_specials';
            for (const op of (batch.operations || [])) {
                if (isStripSpecials || op.op_type === 'waqf_sakt') {
                    op.op_type = 'pipeline';
                }
            }
        }
    }
    historyData.set(data);
    if (!data || !data.batches || data.batches.length === 0) {
        editChains.set(null);
        chainedOpIds.set(null);
        return;
    }
    const built = buildEditChains(data.batches);
    editChains.set(built.chains);
    chainedOpIds.set(built.chainedOpIds);
}

/** Toggle a filter pill in the op-type or category set. */
export function toggleFilter(kind: 'op' | 'cat', value: string): void {
    const store = kind === 'op' ? filterOpTypes : filterErrCats;
    store.update((s) => {
        if (s.has(value)) {
            return new Set();
        } else {
            return new Set([value]);
        }
    });
}

/** Toggle the boolean wasl-annotation filter. Mirrors ``toggleFilter`` but
 *  for a single binary axis: on means "only entries with a wasl boundary
 *  decision", off means "all entries". */
export function toggleWaslFilter(): void {
    filterHasWasl.update((v) => !v);
}

/** Clear all filter axes in a single tick. */
export function clearFilters(): void {
    filterOpTypes.set(new Set());
    filterErrCats.set(new Set());
    filterHasWasl.set(false);
}

/** Set the sort mode (time | quran). */
export function setSortMode(mode: 'time' | 'quran'): void {
    sortMode.set(mode);
}

/** Show/hide the history view. */
export function setHistoryVisible(v: boolean): void {
    historyVisible.set(v);
}

/** Synchronously snapshot derived split chains. */
export function snapshotEditChains(): { chains: Map<string, EditChain> | null; chainedOpIds: Set<string> | null } {
    return { chains: get(editChains), chainedOpIds: get(chainedOpIds) };
}

/** Restore previously-snapshotted split chains. */
export function restoreEditChains(snap: { chains: Map<string, EditChain> | null; chainedOpIds: Set<string> | null }): void {
    editChains.set(snap.chains);
    chainedOpIds.set(snap.chainedOpIds);
}

/** Overwrite split chain state directly (used by undo/discard rebuild). */
export function setEditChains(chains: Map<string, EditChain> | null, ops: Set<string> | null): void {
    editChains.set(chains);
    chainedOpIds.set(ops);
}
