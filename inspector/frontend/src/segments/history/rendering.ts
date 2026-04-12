/**
 * Edit history batch/op rendering, arrows, summary stats, split chain rows.
 * Pure rendering -- no data fetching or filter state mutation.
 */

import { state, dom, EDIT_OP_LABELS, ERROR_CAT_LABELS } from '../state';
import type { HistoryDisplayItem } from '../state';
import { _classifySnapIssues, _deriveOpIssueDelta } from '../validation/categories';
import { renderSegCard } from '../rendering';
import { surahOptionText } from '../../shared/surah-info';
import { onOpUndoClick, onChainUndoClick, onPendingBatchDiscard, _getChainBatchIds } from './undo';
import type { EditOp, HistoryBatch, Segment } from '../../types/domain';
import type { SegCanvas } from '../waveform/types';

/** Narrow view of a snapshot as used by the history renderer. */
type Snapshot = {
    index_at_save?: number;
    segment_uid?: string;
    audio_url?: string;
    time_start: number;
    time_end: number;
    matched_ref?: string;
    matched_text?: string;
    display_text?: string;
    confidence?: number;
    wrap_word_ranges?: unknown;
    has_repeated_words?: boolean;
    [k: string]: unknown;
};

/** Chain operation descriptor (op + enclosing batch). */
interface ChainOp {
    op: EditOp;
    batch?: HistoryBatch | null;
}

/** Split chain built by `_buildSplitChains`. */
interface SplitChain {
    ops: ChainOp[];
    rootSnap?: Snapshot | null;
    rootBatch?: HistoryBatch | null;
    latestDate?: string | null;
    chainId?: string;
}

interface HistSummary {
    total_operations: number;
    chapters_edited: number;
    verses_edited?: number | string;
    op_counts?: Record<string, number>;
    fix_kind_counts?: Record<string, number>;
}

/** Renderer-level flat item built by `_flattenBatchesToItems`. */
interface OpFlatItem {
    type: 'op-card' | 'strip-specials-card' | 'multi-chapter-card' | 'revert-card';
    group: EditOp[];
    chapter: number | null;
    chapters?: number[];
    batchId: string | null;
    date: string;
    isRevert: boolean;
    isPending: boolean;
    batchIdx: number;
    groupIdx: number;
}

type DisplayEntry =
    | { type: 'chain'; chain: SplitChain; date: string }
    | { type: 'op-item'; item: OpFlatItem; date: string };

const SHORT_LABELS: Record<string, string> = {
    failed: 'fail', low_confidence: 'low conf', boundary_adj: 'boundary',
    cross_verse: 'cross', missing_words: 'gaps', audio_bleeding: 'bleed',
    repetitions: 'reps', muqattaat: 'muqattaat', qalqala: 'qalqala',
};

// ---------------------------------------------------------------------------
// renderHistorySummaryStats
// ---------------------------------------------------------------------------

export function renderHistorySummaryStats(
    summary: HistSummary | null | undefined,
    container: HTMLElement = dom.segHistoryStats,
): void {
    container.innerHTML = '';
    if (!summary) return;
    const cardsRow = document.createElement('div');
    cardsRow.className = 'seg-history-stat-cards';
    const stats: Array<{ value: number | string; label: string }> = [
        { value: summary.total_operations, label: 'Operations' },
        { value: summary.chapters_edited, label: 'Chapters' },
        { value: summary.verses_edited ?? '\u2013', label: 'Verses' },
    ];
    for (const s of stats) {
        const card = document.createElement('div');
        card.className = 'seg-history-stat-card';
        card.innerHTML = `<div class="seg-history-stat-value">${s.value}</div><div class="seg-history-stat-label">${s.label}</div>`;
        cardsRow.appendChild(card);
    }
    container.appendChild(cardsRow);
}

// ---------------------------------------------------------------------------
// _versesFromRef / _countVersesFromBatches
// ---------------------------------------------------------------------------

export function _versesFromRef(ref: string | null | undefined): string[] {
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

export function _countVersesFromBatches(batches: HistoryBatch[]): number {
    const verses = new Set<string>();
    for (const batch of batches) {
        for (const op of (batch.operations || [])) {
            for (const snap of [...(op.targets_before || []), ...(op.targets_after || [])]) {
                const matchedRef = (snap as { matched_ref?: string }).matched_ref;
                for (const v of _versesFromRef(matchedRef ?? '')) verses.add(v);
            }
        }
    }
    return verses.size;
}

// ---------------------------------------------------------------------------
// renderHistoryBatches -- top-level batch list renderer
// ---------------------------------------------------------------------------

export function renderHistoryBatches(
    batches: HistoryBatch[],
    container: HTMLElement = dom.segHistoryBatches,
): void {
    const chainedOpIds = state._chainedOpIds || new Set<string>();
    const items = _flattenBatchesToItems(batches, chainedOpIds);
    _renderHistoryDisplayItems(items, batches, container);
}

// ---------------------------------------------------------------------------
// _renderHistoryDisplayItems -- sort + render both chains and op items
// ---------------------------------------------------------------------------

export function _renderHistoryDisplayItems(
    opItems: HistoryDisplayItem[] | OpFlatItem[],
    batches: HistoryBatch[],
    container: HTMLElement,
): void {
    container.innerHTML = '';
    const displayItems: DisplayEntry[] = [];
    if (state._splitChains && state._histFilterErrCats.size === 0) {
        const showSplitChains = state._histFilterOpTypes.size === 0 || state._histFilterOpTypes.has('split_segment');
        if (showSplitChains) {
            const batchOpIds = new Set<string>(batches.flatMap(b => (b.operations || []).map(op => op.op_id)));
            for (const chain of state._splitChains.values() as unknown as IterableIterator<SplitChain>) {
                if (chain.ops.some(({ op }) => batchOpIds.has(op.op_id))) {
                    displayItems.push({ type: 'chain', chain, date: chain.latestDate || '' });
                }
            }
        }
    }
    for (const item of opItems as OpFlatItem[]) {
        displayItems.push({ type: 'op-item', item, date: item.date });
    }

    if (state._histSortMode === 'quran') {
        displayItems.sort((a, b) => {
            const aChap = _histItemChapter(a);
            const bChap = _histItemChapter(b);
            if (aChap !== bChap) return aChap - bChap;
            const aPos = _histItemTimeStart(a);
            const bPos = _histItemTimeStart(b);
            if (aPos !== bPos) return aPos - bPos;
            return b.date.localeCompare(a.date);
        });
    } else {
        displayItems.sort((a, b) => {
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

    for (const di of displayItems) {
        if (di.type === 'chain') container.appendChild(renderSplitChainRow(di.chain));
        else container.appendChild(_renderOpCard(di.item));
    }
}

// ---------------------------------------------------------------------------
// _flattenBatchesToItems -- convert batch array to flat display items
// ---------------------------------------------------------------------------

export function _flattenBatchesToItems(batches: HistoryBatch[], chainedOpIds: Set<string>): OpFlatItem[] {
    const items: OpFlatItem[] = [];
    for (let bIdx = 0; bIdx < batches.length; bIdx++) {
        const batch = batches[bIdx];
        if (!batch) continue;
        const nonChainOps = (batch.operations || []).filter(op => !chainedOpIds.has(op.op_id));
        const isMultiChapter = batch.chapter == null && Array.isArray(batch.chapters);
        const isStripSpecials = batch.batch_type === 'strip_specials';
        if (isStripSpecials) {
            const byRef = new Map<string, EditOp[]>();
            for (const op of nonChainOps) {
                const ref = ((op.targets_before?.[0] as Snapshot | undefined)?.matched_ref) || '(unknown)';
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
            const groups = _groupRelatedOps(nonChainOps);
            for (let gIdx = 0; gIdx < groups.length; gIdx++) {
                items.push({ type: 'op-card', group: groups[gIdx]!, chapter: batch.chapter, chapters: batch.chapters, batchId: batch.batch_id, date: batch.saved_at_utc || '', isRevert: !!batch.is_revert, isPending: !batch.batch_id && !batch.is_revert, batchIdx: bIdx, groupIdx: gIdx });
            }
        }
    }
    return items;
}

// ---------------------------------------------------------------------------
// renderSplitChainRow -- render a collapsed split chain as one card
// ---------------------------------------------------------------------------

export function renderSplitChainRow(chain: SplitChain): HTMLElement {
    const rootSnap = chain.rootSnap ?? null;
    const leafSnaps = _computeChainLeafSnaps(chain);
    const chapter = chain.rootBatch?.chapter ?? null;
    const wrapper = document.createElement('div');
    wrapper.className = 'seg-history-batch seg-history-split-chain';
    const header = document.createElement('div');
    header.className = 'seg-history-batch-header';
    const time = document.createElement('span');
    time.className = 'seg-history-batch-time';
    time.textContent = _formatHistDate(chain.latestDate);
    header.appendChild(time);
    if (chapter != null) {
        const ch = document.createElement('span');
        ch.className = 'seg-history-batch-chapter';
        ch.textContent = surahOptionText(chapter);
        header.appendChild(ch);
    }
    const badge = document.createElement('span');
    badge.className = 'seg-history-batch-ops-count';
    badge.textContent = `Split \u2192 ${leafSnaps.length}`;
    header.appendChild(badge);
    {
        const beforeIssues = new Set<string>();
        if (rootSnap) _classifySnapIssues(rootSnap as unknown as Segment).forEach((i: string) => beforeIssues.add(i));
        const afterIssues = new Set<string>();
        for (const ls of leafSnaps) _classifySnapIssues(ls as unknown as Segment).forEach((i: string) => afterIssues.add(i));
        for (const cat of [...beforeIssues].filter(i => !afterIssues.has(i))) {
            const b = document.createElement('span');
            b.className = 'seg-history-val-delta improved';
            b.textContent = `\u2212${SHORT_LABELS[cat] || cat}`;
            header.appendChild(b);
        }
        for (const cat of [...afterIssues].filter(i => !beforeIssues.has(i))) {
            const b = document.createElement('span');
            b.className = 'seg-history-val-delta regression';
            b.textContent = `+${SHORT_LABELS[cat] || cat}`;
            header.appendChild(b);
        }
    }
    const chainBatchIds = _getChainBatchIds(chain);
    if (chainBatchIds.length > 0) {
        const undoBtn = document.createElement('button');
        undoBtn.className = 'btn btn-sm seg-history-undo-btn';
        undoBtn.textContent = 'Undo';
        undoBtn.addEventListener('click', (e) => { e.stopPropagation(); onChainUndoClick(chainBatchIds, chapter, undoBtn); });
        header.appendChild(undoBtn);
    }
    wrapper.appendChild(header);

    const body = document.createElement('div');
    body.className = 'seg-history-batch-body';
    const diff = document.createElement('div');
    diff.className = 'seg-history-diff';
    const beforeCol = document.createElement('div');
    beforeCol.className = 'seg-history-before';
    const arrowCol = document.createElement('div');
    arrowCol.className = 'seg-history-arrows';
    const arrowSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    arrowSvg.setAttribute('height', '1');
    arrowCol.appendChild(arrowSvg);
    const afterCol = document.createElement('div');
    afterCol.className = 'seg-history-after';

    let wfStart = rootSnap ? rootSnap.time_start : 0;
    let wfEnd = rootSnap ? rootSnap.time_end : 0;
    for (const ls of leafSnaps) { wfStart = Math.min(wfStart, ls.time_start); wfEnd = Math.max(wfEnd, ls.time_end); }
    const wfExpanded = rootSnap && (wfStart < rootSnap.time_start || wfEnd > rootSnap.time_end);

    if (rootSnap) {
        const beforeCard = renderSegCard(_snapToSeg(rootSnap, chapter), { readOnly: true, showChapter: true, showPlayBtn: true });
        beforeCol.appendChild(beforeCard);
        if (wfExpanded) { const bc = beforeCard.querySelector<SegCanvas>('canvas'); if (bc) bc._splitHL = { wfStart, wfEnd, hlStart: rootSnap.time_start, hlEnd: rootSnap.time_end }; }
    }
    if (leafSnaps.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'seg-history-empty';
        empty.textContent = '(all segments deleted)';
        afterCol.appendChild(empty);
    } else {
        for (const leafSnap of leafSnaps) {
            const card = renderSegCard(_snapToSeg(leafSnap, chapter), { readOnly: true, showChapter: true, showPlayBtn: true });
            afterCol.appendChild(card);
            if (rootSnap) { const canvas = card.querySelector<SegCanvas>('canvas'); if (canvas) canvas._splitHL = { wfStart, wfEnd, hlStart: leafSnap.time_start, hlEnd: leafSnap.time_end }; }
        }
    }
    diff.append(beforeCol, arrowCol, afterCol);
    body.appendChild(diff);
    wrapper.appendChild(body);
    return wrapper;
}

// ---------------------------------------------------------------------------
// renderHistoryGroupedOp -- render a group of related operations
// ---------------------------------------------------------------------------

interface RenderOpOptions { skipLabel?: boolean }

export function renderHistoryGroupedOp(
    group: EditOp[],
    chapter: number | null,
    batchId: string | null,
    { skipLabel = false }: RenderOpOptions = {},
): HTMLElement {
    const primary = group[0]!;
    const finalSnaps = new Map<string, Snapshot>();
    for (const op of group) { for (const snap of (op.targets_after || []) as Snapshot[]) { if (snap.segment_uid) finalSnaps.set(snap.segment_uid, snap); } }
    const before = (primary.targets_before || []) as Snapshot[];
    const primaryAfterUids = ((primary.targets_after || []) as Snapshot[]).map(t => t.segment_uid);
    const after = primaryAfterUids.map(uid => uid ? finalSnaps.get(uid) : undefined).filter((s): s is Snapshot => !!s);
    const wrap = document.createElement('div');
    wrap.className = 'seg-history-op seg-history-grouped-op';
    if (!skipLabel) {
        const label = document.createElement('div');
        label.className = 'seg-history-op-label';
        const typeBadge = document.createElement('span');
        typeBadge.className = 'seg-history-op-type-badge';
        typeBadge.textContent = EDIT_OP_LABELS[primary.op_type] || primary.op_type;
        label.appendChild(typeBadge);
        const followUp: Record<string, number> = {};
        for (let i = 1; i < group.length; i++) { const t = group[i]!.op_type; followUp[t] = (followUp[t] || 0) + 1; }
        for (const [t, count] of Object.entries(followUp)) { const fb = document.createElement('span'); fb.className = 'seg-history-op-type-badge secondary'; fb.textContent = '+ ' + (EDIT_OP_LABELS[t] || t) + (count > 1 ? ` x${count}` : ''); label.appendChild(fb); }
        const fixKinds = new Set<string>(group.map(op => op.fix_kind).filter((fk): fk is string => !!fk && fk !== 'manual'));
        for (const fk of fixKinds) { const fkBadge = document.createElement('span'); fkBadge.className = 'seg-history-op-fix-kind'; fkBadge.textContent = fk; label.appendChild(fkBadge); }
        if (batchId) { const groupOpIds = group.map(op => op.op_id); const undoBtn = document.createElement('button'); undoBtn.className = 'btn btn-sm seg-history-op-undo-btn'; undoBtn.textContent = 'Undo'; undoBtn.addEventListener('click', (e) => { e.stopPropagation(); onOpUndoClick(batchId, groupOpIds, undoBtn); }); label.appendChild(undoBtn); }
        wrap.appendChild(label);
    }
    const diff = document.createElement('div');
    diff.className = 'seg-history-diff';
    const beforeCol = document.createElement('div');
    beforeCol.className = 'seg-history-before';
    const arrowCol = document.createElement('div');
    arrowCol.className = 'seg-history-arrows';
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('height', '1');
    arrowCol.appendChild(svg);
    const afterCol = document.createElement('div');
    afterCol.className = 'seg-history-after';
    const beforeCards: HTMLElement[] = [];
    for (const snap of before) { const card = renderSegCard(_snapToSeg(snap, chapter), { readOnly: true, showChapter: true, showPlayBtn: true }); beforeCol.appendChild(card); beforeCards.push(card); }
    const afterCards: HTMLElement[] = [];
    if (after.length === 0) { const empty = document.createElement('div'); empty.className = 'seg-history-empty'; empty.textContent = '(deleted)'; afterCol.appendChild(empty); }
    else { for (const snap of after) { const card = renderSegCard(_snapToSeg(snap, chapter), { readOnly: true, showChapter: true, showPlayBtn: true }); afterCol.appendChild(card); afterCards.push(card); } }
    if (before.length === 1 && after.length === 1 && beforeCards[0] && afterCards[0]) _highlightChanges(before[0]!, after[0]!, beforeCards[0], afterCards[0]);
    if ((primary.op_type === 'merge_segments' || primary.op_type === 'waqf_sakt') && before.length === 2 && afterCards.length === 1) {
        const afterCanvas = afterCards[0]!.querySelector<SegCanvas>('canvas');
        if (afterCanvas && primary.merge_direction) { const hlSnap = primary.merge_direction === 'prev' ? before[1]! : before[0]!; afterCanvas._mergeHL = { hlStart: hlSnap.time_start, hlEnd: hlSnap.time_end }; }
    }
    diff.append(beforeCol, arrowCol, afterCol);
    wrap.appendChild(diff);
    return wrap;
}

// ---------------------------------------------------------------------------
// renderHistoryOp -- render a single operation
// ---------------------------------------------------------------------------

export function renderHistoryOp(
    op: EditOp,
    chapter: number | null,
    batchId: string | null,
    { skipLabel = false }: RenderOpOptions = {},
): HTMLElement {
    const wrap = document.createElement('div');
    wrap.className = 'seg-history-op';
    if (!skipLabel) {
        const label = document.createElement('div');
        label.className = 'seg-history-op-label';
        const typeBadge = document.createElement('span');
        typeBadge.className = 'seg-history-op-type-badge';
        typeBadge.textContent = EDIT_OP_LABELS[op.op_type] || op.op_type;
        label.appendChild(typeBadge);
        if (op.fix_kind && op.fix_kind !== 'manual') { const fk = document.createElement('span'); fk.className = 'seg-history-op-fix-kind'; fk.textContent = op.fix_kind; label.appendChild(fk); }
        if (batchId) { const undoBtn = document.createElement('button'); undoBtn.className = 'btn btn-sm seg-history-op-undo-btn'; undoBtn.textContent = 'Undo'; undoBtn.addEventListener('click', (e) => { e.stopPropagation(); onOpUndoClick(batchId, [op.op_id], undoBtn); }); label.appendChild(undoBtn); }
        wrap.appendChild(label);
    }
    const diff = document.createElement('div');
    diff.className = 'seg-history-diff';
    const beforeCol = document.createElement('div');
    beforeCol.className = 'seg-history-before';
    const arrowCol = document.createElement('div');
    arrowCol.className = 'seg-history-arrows';
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('height', '1');
    arrowCol.appendChild(svg);
    const afterCol = document.createElement('div');
    afterCol.className = 'seg-history-after';
    const before = (op.targets_before || []) as Snapshot[];
    const after = (op.targets_after || []) as Snapshot[];
    const beforeCards: HTMLElement[] = [];
    for (const snap of before) { const pseudoSeg = _snapToSeg(snap, chapter); const card = renderSegCard(pseudoSeg, { readOnly: true, showChapter: true, showPlayBtn: true }); beforeCol.appendChild(card); beforeCards.push(card); }
    const afterCards: HTMLElement[] = [];
    if (after.length === 0) { const empty = document.createElement('div'); empty.className = 'seg-history-empty'; empty.textContent = '(deleted)'; afterCol.appendChild(empty); }
    else { for (const snap of after) { const pseudoSeg = _snapToSeg(snap, chapter); const card = renderSegCard(pseudoSeg, { readOnly: true, showChapter: true, showPlayBtn: true }); afterCol.appendChild(card); afterCards.push(card); } }
    if (before.length === 1 && after.length === 1 && beforeCards[0] && afterCards[0]) _highlightChanges(before[0]!, after[0]!, beforeCards[0], afterCards[0]);
    if ((op.op_type === 'merge_segments' || op.op_type === 'waqf_sakt') && before.length === 2 && afterCards.length === 1) {
        const afterCanvas = afterCards[0]!.querySelector<SegCanvas>('canvas');
        if (afterCanvas && op.merge_direction) { const hlSnap = op.merge_direction === 'prev' ? before[1]! : before[0]!; afterCanvas._mergeHL = { hlStart: hlSnap.time_start, hlEnd: hlSnap.time_end }; }
    }
    diff.append(beforeCol, arrowCol, afterCol);
    wrap.appendChild(diff);
    return wrap;
}

// ---------------------------------------------------------------------------
// _renderOpCard -- render a single display item (op group, chain, revert, etc.)
// ---------------------------------------------------------------------------

export function _renderOpCard(item: OpFlatItem): HTMLElement {
    const wrapper = document.createElement('div');
    wrapper.className = 'seg-history-batch' + (item.isRevert ? ' is-revert' : '');
    const header = document.createElement('div');
    header.className = 'seg-history-batch-header';
    const group = item.group;
    if (item.type === 'strip-specials-card') {
        const badge = document.createElement('span'); badge.className = 'seg-history-op-type-badge'; badge.textContent = `Deletion \u00d7${group.length}`; header.appendChild(badge);
    } else if (item.type === 'multi-chapter-card') {
        const opType = group[0]?.op_type || ''; const badge = document.createElement('span'); badge.className = 'seg-history-op-type-badge'; badge.textContent = `${EDIT_OP_LABELS[opType] || opType} \u00d7${group.length}`; header.appendChild(badge);
    } else if (item.type === 'revert-card') {
        // no op badge
    } else if (group.length > 0) {
        const primary = group[0]!;
        const typeBadge = document.createElement('span'); typeBadge.className = 'seg-history-op-type-badge'; typeBadge.textContent = EDIT_OP_LABELS[primary.op_type] || primary.op_type; header.appendChild(typeBadge);
        const followUp: Record<string, number> = {};
        for (let i = 1; i < group.length; i++) { const t = group[i]!.op_type; followUp[t] = (followUp[t] || 0) + 1; }
        for (const [t, count] of Object.entries(followUp)) { const fb = document.createElement('span'); fb.className = 'seg-history-op-type-badge secondary'; fb.textContent = '+ ' + (EDIT_OP_LABELS[t] || t) + (count > 1 ? ` \u00d7${count}` : ''); header.appendChild(fb); }
    }
    const fixKinds = new Set<string>(group.map(op => op.fix_kind).filter((fk): fk is string => !!fk && fk !== 'manual'));
    if (item.type === 'strip-specials-card' || item.type === 'multi-chapter-card') fixKinds.add('auto_fix');
    for (const fk of fixKinds) { const fkBadge = document.createElement('span'); fkBadge.className = 'seg-history-op-fix-kind'; fkBadge.textContent = fk; header.appendChild(fkBadge); }
    if (group.length > 0) _appendIssueDeltaBadges(header, group);
    if (item.isRevert) { const badge = document.createElement('span'); badge.className = 'seg-history-batch-revert-badge'; badge.textContent = 'Reverted'; header.appendChild(badge); }
    const ch = item.chapter;
    if (ch != null) { const chSpan = document.createElement('span'); chSpan.className = 'seg-history-batch-chapter'; chSpan.textContent = surahOptionText(ch); header.appendChild(chSpan); }
    const time = document.createElement('span'); time.className = 'seg-history-batch-time'; time.textContent = _formatHistDate(item.date || null); header.appendChild(time);
    if (item.isPending) {
        const discardBtn = document.createElement('button'); discardBtn.className = 'btn btn-sm seg-history-undo-btn'; discardBtn.textContent = 'Discard';
        discardBtn.addEventListener('click', (e) => { e.stopPropagation(); if (item.chapter != null) onPendingBatchDiscard(item.chapter, discardBtn); });
        header.appendChild(discardBtn);
    } else if (item.batchId && !item.isRevert) {
        const opIds = group.map(op => op.op_id);
        const undoBtn = document.createElement('button'); undoBtn.className = 'btn btn-sm seg-history-undo-btn'; undoBtn.textContent = 'Undo';
        const batchId = item.batchId;
        undoBtn.addEventListener('click', (e) => { e.stopPropagation(); onOpUndoClick(batchId, opIds, undoBtn); });
        header.appendChild(undoBtn);
    }
    wrapper.appendChild(header);
    if (group.length > 0 || item.type === 'multi-chapter-card') {
        const body = document.createElement('div'); body.className = 'seg-history-batch-body';
        if (item.type === 'strip-specials-card') body.appendChild(_renderSpecialDeleteGroup(group));
        else if (item.type === 'multi-chapter-card') { const chList = document.createElement('div'); chList.className = 'seg-history-chapter-list'; chList.textContent = 'Chapters: ' + (item.chapters || []).map(c => surahOptionText(c)).join(', '); body.appendChild(chList); }
        else if (group.length === 1) body.appendChild(renderHistoryOp(group[0]!, item.chapter, item.batchId, { skipLabel: true }));
        else body.appendChild(renderHistoryGroupedOp(group, item.chapter, item.batchId, { skipLabel: true }));
        wrapper.appendChild(body);
    }
    return wrapper;
}

// ---------------------------------------------------------------------------
// _renderSpecialDeleteGroup
// ---------------------------------------------------------------------------

function _renderSpecialDeleteGroup(refOps: EditOp[]): HTMLElement {
    const count = refOps.length;
    const snap = (refOps[0]?.targets_before?.[0]) as Snapshot | undefined;
    const diffEl = document.createElement('div'); diffEl.className = 'seg-history-diff';
    const beforeCol = document.createElement('div'); beforeCol.className = 'seg-history-before';
    if (snap) beforeCol.appendChild(renderSegCard(_snapToSeg(snap, null), { readOnly: true, showPlayBtn: true }));
    const afterCol = document.createElement('div'); afterCol.className = 'seg-history-after';
    const emptyEl = document.createElement('div'); emptyEl.className = 'seg-history-empty'; emptyEl.textContent = count > 1 ? `\u00d7${count} deleted` : '(deleted)'; afterCol.appendChild(emptyEl);
    diffEl.appendChild(beforeCol); diffEl.appendChild(afterCol);
    return diffEl;
}

// ---------------------------------------------------------------------------
// _groupRelatedOps -- group ops by segment_uid lineage
// ---------------------------------------------------------------------------

export function _groupRelatedOps(operations: EditOp[]): EditOp[][] {
    if (!operations || operations.length === 0) return [];
    if (operations.length === 1) return [[operations[0]!]];
    const groups: EditOp[][] = [];
    const opGroupIdx = new Map<number, number>();
    const uidToGroup = new Map<string, number>();
    for (let i = 0; i < operations.length; i++) {
        const op = operations[i]!;
        const beforeUids = ((op.targets_before || []) as Snapshot[]).map(t => t.segment_uid).filter((u): u is string => !!u);
        let parentGroup: number | null = null;
        for (const uid of beforeUids) { if (uidToGroup.has(uid)) { parentGroup = uidToGroup.get(uid)!; break; } }
        if (parentGroup !== null) { groups[parentGroup]!.push(op); opGroupIdx.set(i, parentGroup); }
        else { const gIdx = groups.length; groups.push([op]); opGroupIdx.set(i, gIdx); }
        const gIdx = opGroupIdx.get(i)!;
        for (const snap of ((op.targets_after || []) as Snapshot[])) { if (snap.segment_uid) uidToGroup.set(snap.segment_uid, gIdx); }
    }
    return groups;
}

// ---------------------------------------------------------------------------
// _snapToSeg / _highlightChanges
// ---------------------------------------------------------------------------

export function _snapToSeg(snap: Snapshot, chapter: number | null): Segment {
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

export function _highlightChanges(beforeSnap: Snapshot, afterSnap: Snapshot, beforeCard: HTMLElement, afterCard: HTMLElement): void {
    if (beforeSnap.matched_ref !== afterSnap.matched_ref) { const el = afterCard.querySelector('.seg-text-ref'); if (el) el.classList.add('seg-history-changed'); }
    if (beforeSnap.time_start !== afterSnap.time_start || beforeSnap.time_end !== afterSnap.time_end) {
        const el = afterCard.querySelector('.seg-text-duration'); if (el) el.classList.add('seg-history-changed');
        const bCanvas = beforeCard.querySelector<SegCanvas>('canvas'); const aCanvas = afterCard.querySelector<SegCanvas>('canvas');
        if (bCanvas) bCanvas._trimHL = { color: 'red', otherStart: afterSnap.time_start, otherEnd: afterSnap.time_end };
        if (aCanvas) aCanvas._trimHL = { color: 'green', otherStart: beforeSnap.time_start, otherEnd: beforeSnap.time_end };
    }
    if (beforeSnap.confidence !== afterSnap.confidence) { const el = afterCard.querySelector('.seg-text-conf'); if (el) el.classList.add('seg-history-changed'); }
    if (beforeSnap.matched_text !== afterSnap.matched_text) { const el = afterCard.querySelector('.seg-text-body'); if (el) el.classList.add('seg-history-changed'); }
}

// ---------------------------------------------------------------------------
// _appendIssueDeltaBadges / _appendValDeltas
// ---------------------------------------------------------------------------

export function _appendIssueDeltaBadges(container: HTMLElement, group: EditOp[]): void {
    const delta = _deriveOpIssueDelta(group);
    for (const cat of delta.resolved) { const badge = document.createElement('span'); badge.className = 'seg-history-val-delta improved'; badge.textContent = `\u2212${SHORT_LABELS[cat] || cat}`; container.appendChild(badge); }
    for (const cat of delta.introduced) { const badge = document.createElement('span'); badge.className = 'seg-history-val-delta regression'; badge.textContent = `+${SHORT_LABELS[cat] || cat}`; container.appendChild(badge); }
}

export function _appendValDeltas(
    container: HTMLElement,
    before: Record<string, unknown> | null | undefined,
    after: Record<string, unknown> | null | undefined,
): void {
    if (!before || !after) return;
    const cats = state._validationCategories || Object.keys(ERROR_CAT_LABELS);
    for (const cat of cats) {
        const beforeVal = Number(before[cat] || 0);
        const afterVal = Number(after[cat] || 0);
        const delta = afterVal - beforeVal;
        if (delta === 0) continue;
        const badge = document.createElement('span');
        badge.className = 'seg-history-val-delta ' + (delta < 0 ? 'improved' : 'regression');
        badge.textContent = `${SHORT_LABELS[cat]} ${delta > 0 ? '+' : ''}${delta}`;
        container.appendChild(badge);
    }
}

// ---------------------------------------------------------------------------
// _formatHistDate
// ---------------------------------------------------------------------------

export function _formatHistDate(isoStr: string | null | undefined): string {
    if (!isoStr) return 'Pending';
    try {
        const d = new Date(isoStr);
        return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    } catch { return isoStr; }
}

// ---------------------------------------------------------------------------
// _ensureHistArrowDefs / drawHistoryArrows / _drawArrowPath
// ---------------------------------------------------------------------------

function _ensureHistArrowDefs(): void {
    if (document.getElementById('hist-arrow-defs')) return;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('id', 'hist-arrow-defs');
    svg.setAttribute('width', '0');
    svg.setAttribute('height', '0');
    svg.style.position = 'absolute';
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
    marker.setAttribute('id', 'hist-arrow');
    marker.setAttribute('viewBox', '0 0 10 7');
    marker.setAttribute('refX', '10');
    marker.setAttribute('refY', '3.5');
    marker.setAttribute('markerWidth', '8');
    marker.setAttribute('markerHeight', '6');
    marker.setAttribute('orient', 'auto-start-reverse');
    const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    poly.setAttribute('points', '0 0, 10 3.5, 0 7');
    poly.setAttribute('fill', '#4cc9f0');
    marker.appendChild(poly);
    defs.appendChild(marker);
    svg.appendChild(defs);
    document.body.appendChild(svg);
}

export function drawHistoryArrows(diffEl: HTMLElement): void {
    _ensureHistArrowDefs();
    const svg = diffEl.querySelector<SVGSVGElement>('.seg-history-arrows svg');
    if (!svg) return;
    const beforeCards = diffEl.querySelectorAll<HTMLElement>('.seg-history-before .seg-row');
    const afterCards = diffEl.querySelectorAll<HTMLElement>('.seg-history-after .seg-row');
    const afterEmpty = diffEl.querySelector<HTMLElement>('.seg-history-after .seg-history-empty');
    svg.innerHTML = '';
    const arrowCol = diffEl.querySelector<HTMLElement>('.seg-history-arrows');
    if (!arrowCol) return;
    const colRect = arrowCol.getBoundingClientRect();
    if (colRect.height < 1) return;
    svg.setAttribute('height', String(colRect.height));
    svg.setAttribute('viewBox', `0 0 60 ${colRect.height}`);
    const midYs = (cards: NodeListOf<HTMLElement>): number[] =>
        Array.from(cards).map(c => { const r = c.getBoundingClientRect(); return r.top + r.height / 2 - colRect.top; });
    const bY = midYs(beforeCards);
    const aY = afterCards.length > 0 ? midYs(afterCards) : [];

    if (afterCards.length === 0 && afterEmpty) {
        const eRect = afterEmpty.getBoundingClientRect();
        const targetY = eRect.top + eRect.height / 2 - colRect.top;
        for (const sy of bY) _drawArrowPath(svg, 4, sy, 56, targetY, true);
        const xSize = 5;
        const xG = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        xG.setAttribute('stroke', '#f44336');
        xG.setAttribute('stroke-width', '2');
        const cx = 52, cy = targetY;
        const l1 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        l1.setAttribute('x1', String(cx - xSize)); l1.setAttribute('y1', String(cy - xSize));
        l1.setAttribute('x2', String(cx + xSize)); l1.setAttribute('y2', String(cy + xSize));
        const l2 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        l2.setAttribute('x1', String(cx - xSize)); l2.setAttribute('y1', String(cy + xSize));
        l2.setAttribute('x2', String(cx + xSize)); l2.setAttribute('y2', String(cy - xSize));
        xG.append(l1, l2);
        svg.appendChild(xG);
        return;
    }
    if (bY.length === 1 && aY.length === 1) { _drawArrowPath(svg, 4, bY[0]!, 56, aY[0]!, false); return; }
    if (bY.length === 1 && aY.length > 1) { for (const ty of aY) _drawArrowPath(svg, 4, bY[0]!, 56, ty, false); return; }
    if (bY.length > 1 && aY.length === 1) { for (const sy of bY) _drawArrowPath(svg, 4, sy, 56, aY[0]!, false); return; }
    const maxLen = Math.max(bY.length, aY.length);
    for (let i = 0; i < maxLen; i++) { const sy = bY[Math.min(i, bY.length - 1)]!; const ty = aY[Math.min(i, aY.length - 1)]!; _drawArrowPath(svg, 4, sy, 56, ty, false); }
}

function _drawArrowPath(svg: SVGSVGElement, x1: number, y1: number, x2: number, y2: number, dashed: boolean): void {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    const midX = (x1 + x2) / 2;
    const d = Math.abs(y2 - y1) < 2
        ? `M ${x1} ${y1} L ${x2} ${y2}`
        : `M ${x1} ${y1} Q ${midX} ${y1}, ${midX} ${(y1 + y2) / 2} Q ${midX} ${y2}, ${x2} ${y2}`;
    path.setAttribute('d', d);
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', '#4cc9f0');
    path.setAttribute('stroke-width', '1.5');
    if (dashed) path.setAttribute('stroke-dasharray', '4,3');
    path.setAttribute('marker-end', 'url(#hist-arrow)');
    svg.appendChild(path);
}

// ---------------------------------------------------------------------------
// _histItemChapter / _histItemTimeStart -- sort helpers
// ---------------------------------------------------------------------------

function _histItemChapter(di: DisplayEntry): number {
    if (di.type === 'chain') return di.chain.rootBatch?.chapter ?? Infinity;
    const item = di.item;
    if (item.chapter != null) return item.chapter;
    if (Array.isArray(item.chapters) && item.chapters.length) return Math.min(...item.chapters);
    return Infinity;
}

function _histItemTimeStart(di: DisplayEntry): number {
    if (di.type === 'chain') return di.chain.rootSnap?.time_start ?? Infinity;
    const firstOp = di.item.group[0];
    const firstSnap = firstOp?.targets_before?.[0] as Snapshot | undefined;
    return firstSnap?.time_start ?? Infinity;
}

// ---------------------------------------------------------------------------
// _computeChainLeafSnaps -- find the final leaf snapshots of a split chain
// ---------------------------------------------------------------------------

function _computeChainLeafSnaps(chain: SplitChain): Snapshot[] {
    const finalSnaps = new Map<string, Snapshot>();
    const beforeUids = new Set<string>();
    for (const { op } of chain.ops) {
        const afterUids = new Set<string>(((op.targets_after || []) as Snapshot[]).map(s => s.segment_uid).filter((u): u is string => !!u));
        for (const snap of ((op.targets_before || []) as Snapshot[])) { if (snap.segment_uid && !afterUids.has(snap.segment_uid)) beforeUids.add(snap.segment_uid); }
        for (const snap of ((op.targets_after || []) as Snapshot[])) { if (snap.segment_uid) finalSnaps.set(snap.segment_uid, snap); }
    }
    return [...finalSnaps.entries()].filter(([uid]) => !beforeUids.has(uid)).map(([, snap]) => snap).sort((a, b) => a.time_start - b.time_start);
}
