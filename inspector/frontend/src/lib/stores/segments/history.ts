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

import type { SegEditHistoryResponse } from '../../types/api';
import type { SplitChain } from '../../types/segments';
import {
    buildSplitChains,
    buildSplitLineage,
} from '../../utils/segments/history-chains';
import { flattenBatchesToItems } from '../../utils/segments/history-items';

// Re-export chain helpers so existing consumers keep one import site.
export {
    buildSplitChains,
    buildSplitLineage,
    computeChainLeafSnaps,
    getChainBatchIds,
    snapToSeg,
    type BuildChainsResult,
    type SplitChain,
    type SplitChainOp,
} from '../../utils/segments/history-chains';

// Re-export item helpers so existing consumers keep one import site.
export {
    buildDisplayItems,
    computeFilteredItemSummary,
    countVersesFromBatches,
    countVersesFromItems,
    flattenBatchesToItems,
    formatHistDate,
    groupRelatedOps,
    histItemChapter,
    histItemTimeStart,
    itemMatchesCatFilter,
    itemMatchesOpFilter,
    SHORT_LABELS,
    versesFromRef,
    type DisplayEntry,
    type FilteredItemSummary,
    type HistorySnapshot,
    type OpFlatItem,
} from '../../utils/segments/history-items';

// ---------------------------------------------------------------------------
// Stores
// ---------------------------------------------------------------------------

/** Raw edit-history response from `/api/seg/edit-history/<reciter>`. */
export const historyData = writable<SegEditHistoryResponse | null>(null);

/** Map of split-chain id (root op_id) → chain descriptor. */
export const splitChains = writable<Map<string, SplitChain> | null>(null);

/** Set of op_ids absorbed into split chains (so they hide from flat items). */
export const chainedOpIds = writable<Set<string> | null>(null);

/** Active op-type filter pills (e.g. {"split_segment"}). */
export const filterOpTypes = writable<Set<string>>(new Set());

/** Active error-category filter pills (e.g. {"low_confidence"}). */
export const filterErrCats = writable<Set<string>>(new Set());

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
    historyData.set(data);
    if (!data || !data.batches || data.batches.length === 0) {
        splitChains.set(null);
        chainedOpIds.set(null);
        return;
    }
    const lineage = buildSplitLineage(data.batches);
    const built = buildSplitChains(data.batches, lineage);
    splitChains.set(built.chains);
    chainedOpIds.set(built.chainedOpIds);
}

/** Toggle a filter pill in the op-type or category set. */
export function toggleFilter(kind: 'op' | 'cat', value: string): void {
    const store = kind === 'op' ? filterOpTypes : filterErrCats;
    store.update((s) => {
        const next = new Set(s);
        if (next.has(value)) next.delete(value); else next.add(value);
        return next;
    });
}

/** Clear both filter sets in a single tick. */
export function clearFilters(): void {
    filterOpTypes.set(new Set());
    filterErrCats.set(new Set());
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
export function snapshotSplitChains(): { chains: Map<string, SplitChain> | null; chainedOpIds: Set<string> | null } {
    return { chains: get(splitChains), chainedOpIds: get(chainedOpIds) };
}

/** Restore previously-snapshotted split chains. */
export function restoreSplitChains(snap: { chains: Map<string, SplitChain> | null; chainedOpIds: Set<string> | null }): void {
    splitChains.set(snap.chains);
    chainedOpIds.set(snap.chainedOpIds);
}

/** Overwrite split chain state directly (used by undo/discard rebuild). */
export function setSplitChains(chains: Map<string, SplitChain> | null, ops: Set<string> | null): void {
    splitChains.set(chains);
    chainedOpIds.set(ops);
}
