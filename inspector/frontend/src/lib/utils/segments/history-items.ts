import type { EditOp, HistoryBatch } from '../../types/domain';
import type {
    HistorySnapshot,
    OpFlatItem,
    SplitChain,
    SplitChainOp,
} from '../../types/segments';
import { _deriveOpIssueDelta } from './classify';

// Re-export for consumers that want these types from a utils path.
export type { HistorySnapshot, OpFlatItem, SplitChain, SplitChainOp };

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

/** Short-label dictionary for issue-delta badges (preserved verbatim). */
export const SHORT_LABELS: Record<string, string> = {
    failed: 'fail', low_confidence: 'low conf', boundary_adj: 'boundary',
    cross_verse: 'cross', missing_words: 'gaps', audio_bleeding: 'bleed',
    repetitions: 'reps', muqattaat: 'muqattaat', qalqala: 'qalqala',
};

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

export function formatHistDate(isoStr: string | null | undefined): string {
    if (!isoStr) return 'Pending';
    try {
        const d = new Date(isoStr);
        return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    } catch { return isoStr; }
}

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

export function itemMatchesOpFilter(item: OpFlatItem, opTypes: Set<string>): boolean {
    return item.group.some((op) => opTypes.has(op.op_type));
}

export function itemMatchesCatFilter(item: OpFlatItem, cats: Set<string>): boolean {
    for (const op of item.group) { if (op.op_context_category && cats.has(op.op_context_category)) return true; }
    const delta = _deriveOpIssueDelta(item.group);
    for (const cat of cats) { if (delta.resolved.includes(cat) || delta.introduced.includes(cat)) return true; }
    return false;
}

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
