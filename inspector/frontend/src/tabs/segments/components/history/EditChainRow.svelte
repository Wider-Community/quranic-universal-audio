<script lang="ts">
    /**
     * SplitChainRow — collapsed split-chain card (root → N leaves).
     *
     * Lays out a single before card (the original segment) on the left and
     * N after cards (the final leaves) on the right, with the shared
     * HistoryArrows column between them.
     *
     * The waveform sub-range is the union of root ± leaf boundaries. When
     * any leaf exceeds the root range the chain is "expanded" and the
     * canvas renders against the wider range via `_splitHL.wfStart/wfEnd`
     * (passed through SegmentRow's reactive splitHL prop).
     */

    import { editGate } from '../../../../lib/actions/editGate';
    import type { Segment } from '../../../../lib/types/domain';
    import { surahOptionText } from '../../../../lib/utils/surah-info';
    import {
        computeChainLeafSnaps,
        type EditChain,
        formatHistDate,
        getChainBatchIds,
        type HistorySnapshot,
        SHORT_LABELS,
        snapToSeg,
    } from '../../stores/history';
    import type { SplitHighlight, TrimHighlight } from '../../types/segments-waveform';
    import type { PreviewPlaybackContext } from '../../utils/playback/preview';
    import { onChainUndoClick, onPendingOpsDiscard } from '../../utils/save/undo';
    import { classifiedIssuesOf } from '../../utils/validation/classified-issues';
    import SegmentRow from '../list/SegmentRow.svelte';
    import HistoryArrows from './HistoryArrows.svelte';

    // Props ------------------------------------------------------------------

    export let chain: EditChain;
    export let previewCtx: PreviewPlaybackContext | undefined = undefined;
    /** `'history'` (default) shows Undo for any saved batches in the chain.
     *  `'preview'` (set by SavePreview) suppresses Undo — that view is for
     *  reviewing pending edits, not reverting prior saves. */
    export let mode: 'preview' | 'history' = 'history';

    // Derived ----------------------------------------------------------------

    $: rootSnap = chain.rootSnap ?? null;
    $: leafSnaps = computeChainLeafSnaps(chain);
    $: chapter = chain.rootBatch?.chapter ?? null;
    $: chainBatchIds = getChainBatchIds(chain);
    /** Op ids whose enclosing batch is unsaved (`batch_id == null`). The
     *  save-preview Discard button hands these to `onPendingOpsDiscard`
     *  so the entire pending chain reverts atomically. */
    $: pendingOpIds = chain.ops
        .filter(({ batch }) => !batch.batch_id)
        .map(({ op }) => op.op_id);

    // Compute waveform range (may exceed root when a leaf went outside).
    $: wfRange = (() => {
        if (!rootSnap) return { wfStart: 0, wfEnd: 0, expanded: false };
        let wfStart = rootSnap.time_start;
        let wfEnd = rootSnap.time_end;
        for (const ls of leafSnaps) {
            if (ls.time_start < wfStart) wfStart = ls.time_start;
            if (ls.time_end > wfEnd) wfEnd = ls.time_end;
        }
        const expanded = wfStart < rootSnap.time_start || wfEnd > rootSnap.time_end;
        return { wfStart, wfEnd, expanded };
    })();

    $: chainOpType = chain.ops[0]?.op.op_type;
    $: isSplit = chainOpType === 'split_segment';
    $: isMerge = chainOpType === 'merge_segments';

    // Root card gets splitHL only when the range is expanded (and only for splits)
    $: rootSplitHL = (() => {
        if (!isSplit || !rootSnap || !wfRange.expanded) return null;
        const hl: SplitHighlight = {
            wfStart: wfRange.wfStart,
            wfEnd: wfRange.wfEnd,
            hlStart: rootSnap.time_start,
            hlEnd: rootSnap.time_end,
        };
        return hl;
    })();

    // Each leaf card gets a splitHL pointing to its own range within wfRange (only for splits)
    function leafSplitHL(leaf: HistorySnapshot): SplitHighlight | null {
        if (!isSplit || !rootSnap) return null;
        return {
            wfStart: wfRange.wfStart,
            wfEnd: wfRange.wfEnd,
            hlStart: leaf.time_start,
            hlEnd: leaf.time_end,
        };
    }

    // Merge highlight for the result card
    $: leafMergeHL = (() => {
        if (!isMerge) return null;
        const mergeOp = chain.ops.find(co => co.op.op_type === 'merge_segments')?.op;
        if (!mergeOp || !mergeOp.targets_before || mergeOp.targets_before.length < 2) return null;
        const b = mergeOp.targets_before as HistorySnapshot[];
        const hlSnap = mergeOp.merge_direction === 'prev' ? b[1]! : b[0]!;
        const mergePoint = mergeOp.merge_direction === 'prev' ? hlSnap.time_start : hlSnap.time_end;
        return { mergePoint };
    })();

    // Trim highlight for chains that include an adjust operation
    $: leafTrimHL = (() => {
        const trimOp = chain.ops.find(co => co.op.op_type === 'boundary_adjustment' || co.op.op_type === 'trim_segment')?.op;
        if (!trimOp || !trimOp.targets_before || trimOp.targets_before.length === 0) return null;
        const b = trimOp.targets_before[0] as HistorySnapshot;
        return { color: 'green', otherStart: b.time_start, otherEnd: b.time_end } as TrimHighlight;
    })();

    // Leaf cards need a wider seg range when expanded so the canvas
    // renders against the chain's union. The IntersectionObserver callback
    // uses splitHL.wfStart/wfEnd to substitute the sub-range
    // (see waveform/index.ts).
    function rootSegForCard(s: HistorySnapshot): Segment {
        return snapToSeg(s, chapter);
    }

    // Validation-delta badges (resolved / regressed issues over the chain).
    // Reads `classified_issues` directly off saved snapshots; absent on
    // unsaved chains (next save+validate cycle resurfaces any pending state).
    $: valDelta = (() => {
        const beforeIssues = new Set<string>();
        if (rootSnap) {
            for (const i of classifiedIssuesOf(rootSnap)) beforeIssues.add(i);
        }
        const afterIssues = new Set<string>();
        for (const ls of leafSnaps) {
            for (const i of classifiedIssuesOf(ls)) afterIssues.add(i);
        }
        const improved = [...beforeIssues].filter((i) => !afterIssues.has(i));
        const regressed = [...afterIssues].filter((i) => !beforeIssues.has(i));
        return { improved, regressed };
    })();

    // Arrow column refs ------------------------------------------------------
    let beforeCardEls: (HTMLElement | undefined)[] = [];
    let afterCardEls: (HTMLElement | undefined)[] = [];
    let arrowsBefore: HTMLElement[] = [];
    let arrowsAfter: HTMLElement[] = [];

    $: chainBadgeText = (() => {
        if (chainOpType === 'split_segment') return `Split \u2192 ${leafSnaps.length}`;
        if (chainOpType === 'merge_segments') return `Merge \u2192 ${leafSnaps.length}`;
        return `Multiple Edits \u2192 ${leafSnaps.length}`;
    })();

    $: {
        arrowsBefore = beforeCardEls.filter((e): e is HTMLElement => !!e);
        arrowsAfter = afterCardEls.filter((e): e is HTMLElement => !!e);
    }

    function handleChainUndoClick(e: MouseEvent): void {
        const btn = e.currentTarget as HTMLButtonElement;
        void onChainUndoClick(chainBatchIds, chapter, btn);
    }

    function handleChainDiscardClick(e: MouseEvent): void {
        if (chapter == null || pendingOpIds.length === 0) return;
        const btn = e.currentTarget as HTMLButtonElement;
        onPendingOpsDiscard(chapter, pendingOpIds, btn);
    }
</script>

<div class="seg-history-batch seg-history-split-chain">
    <div class="seg-history-batch-header">
        <span class="seg-history-batch-time">{formatHistDate(chain.latestDate)}</span>
        {#if chapter != null}
            <span class="seg-history-batch-chapter">{surahOptionText(chapter)}</span>
        {/if}
        <span class="seg-history-batch-ops-count">{chainBadgeText}</span>
        {#each valDelta.improved as cat}
            <span class="seg-history-val-delta improved">&minus;{SHORT_LABELS[cat] || cat}</span>
        {/each}
        {#each valDelta.regressed as cat}
            <span class="seg-history-val-delta regression">+{SHORT_LABELS[cat] || cat}</span>
        {/each}
        {#if mode === 'history' && chainBatchIds.length > 0}
            <button
                class="btn btn-sm seg-history-undo-btn"
                use:editGate
                on:click|stopPropagation={handleChainUndoClick}
            >Undo</button>
        {/if}
        {#if pendingOpIds.length > 0 && chapter != null}
            <button
                class="btn btn-sm seg-history-undo-btn"
                use:editGate
                on:click|stopPropagation={handleChainDiscardClick}
            >Discard</button>
        {/if}
    </div>

    <div class="seg-history-batch-body">
        <div class="seg-history-diff">
            <div class="seg-history-before">
                {#if rootSnap}
                    <div bind:this={beforeCardEls[0]}>
                        <SegmentRow
                            seg={rootSegForCard(rootSnap)}
                            readOnly={true}
                            showChapter={true}
                            showPlayBtn={true}
                            mode="history"
                            instanceRole="history"
                            splitHL={rootSplitHL}
                            opId={chain.ops[0]?.op.op_id ?? null}
                            {previewCtx}
                        />
                    </div>
                {/if}
            </div>

            <div class="seg-history-arrows">
                <HistoryArrows
                    beforeCards={arrowsBefore}
                    afterCards={arrowsAfter}
                    emptyEl={null}
                />
            </div>

            <div class="seg-history-after">
                {#if leafSnaps.length === 0}
                    <div class="seg-history-empty">(all segments deleted)</div>
                {:else}
                    {#each leafSnaps as leaf, i (leaf.segment_uid ?? i)}
                        <div bind:this={afterCardEls[i]}>
                            <SegmentRow
                                seg={snapToSeg(leaf, chapter)}
                                readOnly={true}
                                showChapter={true}
                                showPlayBtn={true}
                                mode="history"
                                instanceRole="history"
                                splitHL={leafSplitHL(leaf)}
                                mergeHL={leafMergeHL}
                                trimHL={leafTrimHL}
                                opId={chain.ops[0]?.op.op_id ?? null}
                                {previewCtx}
                            />
                        </div>
                    {/each}
                {/if}
            </div>
        </div>
    </div>
</div>
