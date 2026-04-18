/**
 * Segments tab — edit-history view store + pure helpers.
 *
 * Single writable owning all history-panel UI state (raw response,
 * derived split chains, filter sets, sort mode, panel visibility) plus the
 * pure helpers.
 *
 * ## Helpers exported
 * - Pure data shapers: `flattenBatchesToItems`, `groupRelatedOps`,
 *   `versesFromRef`, `countVersesFromBatches`, `countVersesFromItems`,
 *   `snapToSeg`, `formatHistDate`, `computeChainLeafSnaps`,
 *   `histItemChapter`, `histItemTimeStart`, `computeFilteredItemSummary`,
 *   `itemMatchesOpFilter`, `itemMatchesCatFilter`,
 *   `buildSplitLineage`, `buildSplitChains`, `getChainBatchIds`.
 * - Derived display ordering: `buildDisplayItems(items, batches, sortMode,
 *   splitChains, filterErrCats, filterOpTypes)`.
 *
 * ## Notes
 * - `histItemChapter` returns `Infinity` sentinel for missing chapters.
 * - `groupRelatedOps` uses union-find lineage.
 * - Split chain filter interaction is in `buildDisplayItems`.
 */

import { derived, get, writable } from 'svelte/store';

import type { SegEditHistoryResponse } from '../../types/api';
import type { EditOp, HistoryBatch, Segment } from '../../types/domain';
import type {
    HistorySnapshot,
    OpFlatItem,
    SplitChain,
    SplitChainOp,
} from '../../types/segments';
import { _deriveOpIssueDelta } from '../../utils/segments/classify';

// ---------------------------------------------------------------------------
// Re-exported helper types
// ---------------------------------------------------------------------------

/** Display entry produced by `buildDisplayItems` for the batches list. */
export type DisplayEntry =
    | { type: 'chain'; chain: SplitChain; date: string }
    | { type: 'op-item'; item: OpFlatItem; date: string };

/** Flat history summary returned by `computeFilteredItemSummary`. */
export interface FilteredItemSummary {
    total_operations: number;
    chapters_edited: number;
    verses_edited: number;
    op_counts: Record<string, number>;
    fix_kind_counts: Record<string, number>;
}

/** Internal result type for `buildSplitChains`. */
export interface BuildChainsResult {
    chains: Map<string, SplitChain>;
    chainedOpIds: Set<string>;
}

/** Internal lineage map produced by `buildSplitLineage`. */
interface SplitLineageEntry {
    wfStart: number;
    wfEnd: number;
    audioUrl: string;
}
type SplitLineage = Map<string, SplitLineageEntry>;

/** Short-label dictionary for issue-delta badges (preserved verbatim). */
export const SHORT_LABELS: Record<string, string> = {
    failed: 'fail', low_confidence: 'low conf', boundary_adj: 'boundary',
    cross_verse: 'cross', missing_words: 'gaps', audio_bleeding: 'bleed',
    repetitions: 'reps', muqattaat: 'muqattaat', qalqala: 'qalqala',
};

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
 * Mirrors the prior imperative `renderEditHistoryPanel` (history/index.ts)
 * preamble. Pass `null` to clear (e.g. on reciter change).
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

/** Show/hide the history view. SegmentsTab hides the normal-content block
 *  reactively via `$historyVisible`. */
export function setHistoryVisible(v: boolean): void {
    historyVisible.set(v);
}

/** Synchronously snapshot derived split chains (used by save preview which
 *  also needs to swap chain state without going through an async tick). */
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

// ---------------------------------------------------------------------------
// _buildSplitLineage / _buildSplitChains — preserved verbatim from
// segments/history/index.ts. Pure functions, no store side effects.
// ---------------------------------------------------------------------------

export function buildSplitLineage(allBatches: HistoryBatch[]): SplitLineage {
    const lineage: SplitLineage = new Map();
    for (const batch of allBatches) {
        for (const op of (batch.operations || [])) {
            if (op.op_type !== 'split_segment') continue;
            const parent = op.targets_before?.[0] as { segment_uid?: string; time_start?: number; time_end?: number; audio_url?: string } | undefined;
            if (!parent) continue;
            const parentCtx: SplitLineageEntry = (parent.segment_uid && lineage.has(parent.segment_uid))
                ? lineage.get(parent.segment_uid)!
                : { wfStart: parent.time_start ?? 0, wfEnd: parent.time_end ?? 0, audioUrl: parent.audio_url ?? '' };
            for (const child of (op.targets_after || []) as Array<{ segment_uid?: string }>) {
                if (child.segment_uid) lineage.set(child.segment_uid, parentCtx);
            }
        }
    }
    return lineage;
}

export function buildSplitChains(allBatches: HistoryBatch[], splitLineage: SplitLineage): BuildChainsResult {
    const chains = new Map<string, SplitChain>();
    const chained = new Set<string>();
    const uidToChain = new Map<string, string>();

    for (const batch of allBatches) {
        for (const op of (batch.operations || [])) {
            if (op.op_type !== 'split_segment') continue;
            const parentBefore = op.targets_before?.[0] as { segment_uid?: string } | undefined;
            const parentUid = parentBefore?.segment_uid;
            if (parentUid && splitLineage.has(parentUid)) continue;
            chains.set(op.op_id, {
                rootSnap: op.targets_before?.[0] as HistorySnapshot | undefined,
                rootBatch: batch,
                ops: [{ op, batch }],
                latestDate: batch.saved_at_utc || '',
            });
            chained.add(op.op_id);
            for (const snap of (op.targets_after || []) as Array<{ segment_uid?: string }>) {
                if (snap.segment_uid) uidToChain.set(snap.segment_uid, op.op_id);
            }
        }
    }

    const _CHAIN_ABSORB_OPS = new Set(['trim_segment', 'split_segment', 'edit_reference', 'confirm_reference']);
    for (const batch of allBatches) {
        for (const op of (batch.operations || [])) {
            if (chained.has(op.op_id)) continue;
            if (!_CHAIN_ABSORB_OPS.has(op.op_type)) continue;
            const beforeUids = ((op.targets_before || []) as Array<{ segment_uid?: string }>).map((s) => s.segment_uid).filter((u): u is string => !!u);
            let chainId: string | null = null;
            for (const uid of beforeUids) { if (uidToChain.has(uid)) { chainId = uidToChain.get(uid)!; break; } }
            if (!chainId) continue;
            const chain = chains.get(chainId);
            if (!chain) continue;
            chain.ops.push({ op, batch });
            if ((batch.saved_at_utc || '') > chain.latestDate) chain.latestDate = batch.saved_at_utc || '';
            chained.add(op.op_id);
            for (const snap of (op.targets_after || []) as Array<{ segment_uid?: string }>) {
                if (snap.segment_uid) uidToChain.set(snap.segment_uid, chainId);
            }
        }
    }

    return { chains, chainedOpIds: chained };
}

// ---------------------------------------------------------------------------
// flattenBatchesToItems — preserved verbatim from
// segments/history/rendering.ts. Decides single op-card / strip-specials /
// multi-chapter / revert-card type per batch, applying union-find grouping.
// ---------------------------------------------------------------------------

export function flattenBatchesToItems(batches: HistoryBatch[], chainedOps: Set<string>): OpFlatItem[] {
    const items: OpFlatItem[] = [];
    for (let bIdx = 0; bIdx < batches.length; bIdx++) {
        const batch = batches[bIdx];
        if (!batch) continue;
        const nonChainOps = (batch.operations || []).filter((op) => !chainedOps.has(op.op_id));
        const isMultiChapter = batch.chapter == null && Array.isArray(batch.chapters);
        const isStripSpecials = batch.batch_type === 'strip_specials';
        if (isStripSpecials) {
            const byRef = new Map<string, EditOp[]>();
            for (const op of nonChainOps) {
                const ref = ((op.targets_before?.[0] as HistorySnapshot | undefined)?.matched_ref) || '(unknown)';
                if (!byRef.has(ref)) byRef.set(ref, []);
                byRef.get(ref)!.push(op);
            }
            let gIdx = 0;
            for (const [, refOps] of byRef) {
                items.push({ type: 'strip-specials-card', group: refOps, chapter: batch.chapter, chapters: batch.chapters, batchId: batch.batch_id, date: batch.saved_at_utc || '', isRevert: !!batch.is_revert, isPending: !batch.batch_id && !batch.is_revert, batchIdx: bIdx, groupIdx: gIdx++ });
            }
        } else if (isMultiChapter) {
            items.push({ type: 'multi-chapter-card', group: nonChainOps, chapter: batch.chapter, chapters: batch.chapters, batchId: batch.batch_id, date: batch.saved_at_utc || '', isRevert: !!batch.is_revert, isPending: !batch.batch_id && !batch.is_revert, batchIdx: bIdx, groupIdx: 0 });
        } else if (batch.is_revert && nonChainOps.length === 0) {
            items.push({ type: 'revert-card', group: [], chapter: batch.chapter, chapters: batch.chapters, batchId: batch.batch_id, date: batch.saved_at_utc || '', isRevert: true, isPending: false, batchIdx: bIdx, groupIdx: 0 });
        } else {
            const groups = groupRelatedOps(nonChainOps);
            for (let gIdx = 0; gIdx < groups.length; gIdx++) {
                items.push({ type: 'op-card', group: groups[gIdx]!, chapter: batch.chapter, chapters: batch.chapters, batchId: batch.batch_id, date: batch.saved_at_utc || '', isRevert: !!batch.is_revert, isPending: !batch.batch_id && !batch.is_revert, batchIdx: bIdx, groupIdx: gIdx });
            }
        }
    }
    return items;
}

// ---------------------------------------------------------------------------
// groupRelatedOps — Risk #5 union-find lineage, preserved verbatim.
// ---------------------------------------------------------------------------

export function groupRelatedOps(operations: EditOp[]): EditOp[][] {
    if (!operations || operations.length === 0) return [];
    if (operations.length === 1) return [[operations[0]!]];
    const groups: EditOp[][] = [];
    const opGroupIdx = new Map<number, number>();
    const uidToGroup = new Map<string, number>();
    for (let i = 0; i < operations.length; i++) {
        const op = operations[i]!;
        const beforeUids = ((op.targets_before || []) as HistorySnapshot[]).map((t) => t.segment_uid).filter((u): u is string => !!u);
        let parentGroup: number | null = null;
        for (const uid of beforeUids) { if (uidToGroup.has(uid)) { parentGroup = uidToGroup.get(uid)!; break; } }
        if (parentGroup !== null) { groups[parentGroup]!.push(op); opGroupIdx.set(i, parentGroup); }
        else { const gIdx = groups.length; groups.push([op]); opGroupIdx.set(i, gIdx); }
        const gIdx = opGroupIdx.get(i)!;
        for (const snap of ((op.targets_after || []) as HistorySnapshot[])) { if (snap.segment_uid) uidToGroup.set(snap.segment_uid, gIdx); }
    }
    return groups;
}

// ---------------------------------------------------------------------------
// snapToSeg — convert a HistorySnapshot to a Segment-shaped object so the
// SegmentRow rendering pipeline can use it.
// ---------------------------------------------------------------------------

export function snapToSeg(snap: HistorySnapshot, chapter: number | null): Segment {
    return {
        index: snap.index_at_save ?? 0,
        entry_idx: 0,
        chapter: chapter ?? undefined,
        audio_url: snap.audio_url || '',
        time_start: snap.time_start, time_end: snap.time_end,
        matched_ref: snap.matched_ref || '', matched_text: snap.matched_text || '',
        display_text: snap.display_text || '', confidence: snap.confidence ?? 0,
        ...(snap.wrap_word_ranges ? { wrap_word_ranges: snap.wrap_word_ranges } : {}),
        ...(snap.has_repeated_words ? { has_repeated_words: true } : {}),
    };
}

// ---------------------------------------------------------------------------
// versesFromRef / countVersesFromBatches / countVersesFromItems
// ---------------------------------------------------------------------------

export function versesFromRef(ref: string | null | undefined): string[] {
    if (!ref) return [];
    const parts = ref.split('-');
    if (parts.length !== 2) return [];
    const sb = parts[0]!.split(':'), se = parts[1]!.split(':');
    if (sb.length < 2 || se.length < 2) return [];
    const surah = parseInt(sb[0]!), ayahStart = parseInt(sb[1]!);
    const surahEnd = parseInt(se[0]!), ayahEnd = parseInt(se[1]!);
    if (surah !== surahEnd) return [`${surah}:${ayahStart}`, `${surahEnd}:${ayahEnd}`];
    const out: string[] = [];
    for (let a = ayahStart; a <= ayahEnd; a++) out.push(`${surah}:${a}`);
    return out;
}

export function countVersesFromBatches(batches: HistoryBatch[]): number {
    const verses = new Set<string>();
    for (const batch of batches) {
        for (const op of (batch.operations || [])) {
            for (const snap of [...(op.targets_before || []), ...(op.targets_after || [])]) {
                const matchedRef = (snap as { matched_ref?: string }).matched_ref;
                for (const v of versesFromRef(matchedRef ?? '')) verses.add(v);
            }
        }
    }
    return verses.size;
}

export function countVersesFromItems(items: OpFlatItem[]): number {
    const verses = new Set<string>();
    for (const item of items) {
        for (const op of item.group) {
            for (const snap of [...(op.targets_before || []), ...(op.targets_after || [])]) {
                const matchedRef = (snap as { matched_ref?: string }).matched_ref;
                for (const v of versesFromRef(matchedRef ?? '')) verses.add(v);
            }
        }
    }
    return verses.size;
}

// ---------------------------------------------------------------------------
// formatHistDate — short locale date+time, "Pending" when no ISO.
// ---------------------------------------------------------------------------

export function formatHistDate(isoStr: string | null | undefined): string {
    if (!isoStr) return 'Pending';
    try {
        const d = new Date(isoStr);
        return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    } catch { return isoStr; }
}

// ---------------------------------------------------------------------------
// computeChainLeafSnaps — find final leaf snapshots of a split chain.
// ---------------------------------------------------------------------------

export function computeChainLeafSnaps(chain: SplitChain): HistorySnapshot[] {
    const finalSnaps = new Map<string, HistorySnapshot>();
    const beforeUids = new Set<string>();
    for (const { op } of chain.ops) {
        const afterUids = new Set<string>(((op.targets_after || []) as HistorySnapshot[]).map((s) => s.segment_uid).filter((u): u is string => !!u));
        for (const snap of ((op.targets_before || []) as HistorySnapshot[])) { if (snap.segment_uid && !afterUids.has(snap.segment_uid)) beforeUids.add(snap.segment_uid); }
        for (const snap of ((op.targets_after || []) as HistorySnapshot[])) { if (snap.segment_uid) finalSnaps.set(snap.segment_uid, snap); }
    }
    return [...finalSnaps.entries()].filter(([uid]) => !beforeUids.has(uid)).map(([, snap]) => snap).sort((a, b) => a.time_start - b.time_start);
}

// ---------------------------------------------------------------------------
// histItemChapter / histItemTimeStart — sort helpers. Risk #4 sentinel
// (`Infinity` for missing chapter) preserved verbatim.
// ---------------------------------------------------------------------------

export function histItemChapter(di: DisplayEntry): number {
    if (di.type === 'chain') return di.chain.rootBatch?.chapter ?? Infinity;
    const item = di.item;
    if (item.chapter != null) return item.chapter;
    if (Array.isArray(item.chapters) && item.chapters.length) return Math.min(...item.chapters);
    return Infinity;
}

export function histItemTimeStart(di: DisplayEntry): number {
    if (di.type === 'chain') return di.chain.rootSnap?.time_start ?? Infinity;
    const firstOp = di.item.group[0];
    const firstSnap = firstOp?.targets_before?.[0] as HistorySnapshot | undefined;
    return firstSnap?.time_start ?? Infinity;
}

// ---------------------------------------------------------------------------
// Filter match helpers
// ---------------------------------------------------------------------------

export function itemMatchesOpFilter(item: OpFlatItem, opTypes: Set<string>): boolean {
    return item.group.some((op) => opTypes.has(op.op_type));
}

export function itemMatchesCatFilter(item: OpFlatItem, cats: Set<string>): boolean {
    for (const op of item.group) { if (op.op_context_category && cats.has(op.op_context_category)) return true; }
    const delta = _deriveOpIssueDelta(item.group);
    for (const cat of cats) { if (delta.resolved.includes(cat) || delta.introduced.includes(cat)) return true; }
    return false;
}

// ---------------------------------------------------------------------------
// computeFilteredItemSummary — summary card stats over a filtered subset.
// ---------------------------------------------------------------------------

export function computeFilteredItemSummary(items: OpFlatItem[]): FilteredItemSummary {
    const opCounts: Record<string, number> = {};
    const fixKindCounts: Record<string, number> = {};
    const chaptersEdited = new Set<number>();
    for (const item of items) {
        if (item.chapter != null) chaptersEdited.add(item.chapter);
        if (Array.isArray(item.chapters)) item.chapters.forEach((ch) => chaptersEdited.add(ch));
        for (const op of item.group) {
            opCounts[op.op_type] = (opCounts[op.op_type] || 0) + 1;
            const kind = op.fix_kind || 'unknown';
            fixKindCounts[kind] = (fixKindCounts[kind] || 0) + 1;
        }
    }
    return {
        total_operations: Object.values(opCounts).reduce((s, v) => s + v, 0),
        chapters_edited: chaptersEdited.size,
        verses_edited: countVersesFromItems(items),
        op_counts: opCounts,
        fix_kind_counts: fixKindCounts,
    };
}

// ---------------------------------------------------------------------------
// buildDisplayItems — combine split chains (filtered per Risk #6) with
// flat op items, then sort by mode. Returns the final ordered list the
// batches container renders.
// ---------------------------------------------------------------------------

export function buildDisplayItems(
    items: OpFlatItem[],
    batches: HistoryBatch[],
    mode: 'time' | 'quran',
    chains: Map<string, SplitChain> | null,
    fOpTypes: Set<string>,
    fErrCats: Set<string>,
): DisplayEntry[] {
    const out: DisplayEntry[] = [];
    if (chains && fErrCats.size === 0) {
        const showSplitChains = fOpTypes.size === 0 || fOpTypes.has('split_segment');
        if (showSplitChains) {
            const batchOpIds = new Set<string>(batches.flatMap((b) => (b.operations || []).map((op) => op.op_id)));
            for (const chain of chains.values()) {
                if (chain.ops.some(({ op }) => batchOpIds.has(op.op_id))) {
                    out.push({ type: 'chain', chain, date: chain.latestDate || '' });
                }
            }
        }
    }
    for (const item of items) {
        out.push({ type: 'op-item', item, date: item.date });
    }

    if (mode === 'quran') {
        out.sort((a, b) => {
            const aChap = histItemChapter(a);
            const bChap = histItemChapter(b);
            if (aChap !== bChap) return aChap - bChap;
            const aPos = histItemTimeStart(a);
            const bPos = histItemTimeStart(b);
            if (aPos !== bPos) return aPos - bPos;
            return b.date.localeCompare(a.date);
        });
    } else {
        out.sort((a, b) => {
            const cmp = b.date.localeCompare(a.date);
            if (cmp !== 0) return cmp;
            if (a.type === 'chain' && b.type !== 'chain') return -1;
            if (b.type === 'chain' && a.type !== 'chain') return 1;
            const aBIdx = a.type === 'op-item' ? a.item.batchIdx : 0;
            const bBIdx = b.type === 'op-item' ? b.item.batchIdx : 0;
            if (aBIdx !== bBIdx) return bBIdx - aBIdx;
            const aGIdx = a.type === 'op-item' ? a.item.groupIdx : 0;
            const bGIdx = b.type === 'op-item' ? b.item.groupIdx : 0;
            return aGIdx - bGIdx;
        });
    }
    return out;
}

// ---------------------------------------------------------------------------
// getChainBatchIds — collect distinct batch ids from a chain in latest-first
// order. Used by chain-undo to reverse them in order.
// ---------------------------------------------------------------------------

export function getChainBatchIds(chain: SplitChain): string[] {
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

// Re-export helper types so consumers can avoid importing from the
// segments/state.ts hub (and to keep the SplitChainOp tagged for callers).
export type { HistorySnapshot, OpFlatItem, SplitChain, SplitChainOp };
