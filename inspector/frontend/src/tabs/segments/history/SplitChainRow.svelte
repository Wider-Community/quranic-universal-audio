<script lang="ts">
    /**
     * SplitChainRow — collapsed split-chain card (root → N leaves).
     *
     * Wave 10 replacement for the imperative `renderSplitChainRow`
     * (segments/history/rendering.ts). Lays out a single before card (the
     * original segment) on the left and N after cards (the final leaves)
     * on the right, with the shared HistoryArrows column in between.
     *
     * The waveform sub-range is computed from the union of root ± leaf
     * boundaries — when a leaf exceeds the root range the chain is
     * "expanded" and the canvas is told to render against the wider
     * range with `_splitHL.wfStart / wfEnd`. The highlight descriptor
     * reaches the canvas via SegmentRow's reactive splitHL prop.
     *
     * Undo button wires to imperative `onChainUndoClick`. Validation
     * delta badges follow the verbatim pre-Wave-10 logic.
     */

    import SegmentRow from '../SegmentRow.svelte';
    import HistoryArrows from './HistoryArrows.svelte';
    import { surahOptionText } from '../../../lib/utils/surah-info';
    import {
        computeChainLeafSnaps,
        formatHistDate,
        getChainBatchIds,
        SHORT_LABELS,
        snapToSeg,
        type HistorySnapshot,
        type SplitChain,
    } from '../../../lib/stores/segments/history';
    import { onChainUndoClick } from '../../../lib/utils/segments/undo';
    import { _classifySnapIssues } from '../../../lib/utils/segments/classify';
    import type { SplitHighlight } from '../../../lib/types/segments-waveform';
    import type { Segment } from '../../../lib/types/domain';

    // Props ------------------------------------------------------------------

    export let chain: SplitChain;

    // Derived ----------------------------------------------------------------

    $: rootSnap = chain.rootSnap ?? null;
    $: leafSnaps = computeChainLeafSnaps(chain);
    $: chapter = chain.rootBatch?.chapter ?? null;
    $: chainBatchIds = getChainBatchIds(chain);

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

    // Root card gets splitHL only when the range is expanded (so the
    // original segment's boundaries are highlighted inside the wider wf).
    $: rootSplitHL = (() => {
        if (!rootSnap || !wfRange.expanded) return null;
        const hl: SplitHighlight = {
            wfStart: wfRange.wfStart,
            wfEnd: wfRange.wfEnd,
            hlStart: rootSnap.time_start,
            hlEnd: rootSnap.time_end,
        };
        return hl;
    })();

    // Each leaf card gets a splitHL pointing to its own range within
    // wfRange — matches the pre-Wave-10 behavior verbatim.
    function leafSplitHL(leaf: HistorySnapshot): SplitHighlight | null {
        if (!rootSnap) return null;
        return {
            wfStart: wfRange.wfStart,
            wfEnd: wfRange.wfEnd,
            hlStart: leaf.time_start,
            hlEnd: leaf.time_end,
        };
    }

    // Leaf cards need a wider seg range when expanded so the canvas
    // renders against the chain's union. The IntersectionObserver callback
    // uses splitHL.wfStart/wfEnd to substitute the sub-range
    // (see waveform/index.ts).
    function rootSegForCard(s: HistorySnapshot): Segment {
        return snapToSeg(s, chapter);
    }

    // Validation-delta badges (resolved / regressed issues over the chain).
    $: valDelta = (() => {
        const beforeIssues = new Set<string>();
        if (rootSnap) {
            for (const i of _classifySnapIssues(rootSnap as unknown as Segment)) beforeIssues.add(i);
        }
        const afterIssues = new Set<string>();
        for (const ls of leafSnaps) {
            for (const i of _classifySnapIssues(ls as unknown as Segment)) afterIssues.add(i);
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
    $: {
        arrowsBefore = beforeCardEls.filter((e): e is HTMLElement => !!e);
        arrowsAfter = afterCardEls.filter((e): e is HTMLElement => !!e);
    }

    function handleChainUndoClick(e: MouseEvent): void {
        const btn = e.currentTarget as HTMLButtonElement;
        void onChainUndoClick(chainBatchIds, chapter, btn);
    }
</script>

<div class="seg-history-batch seg-history-split-chain">
    <div class="seg-history-batch-header">
        <span class="seg-history-batch-time">{formatHistDate(chain.latestDate)}</span>
        {#if chapter != null}
            <span class="seg-history-batch-chapter">{surahOptionText(chapter)}</span>
        {/if}
        <span class="seg-history-batch-ops-count">Split &rarr; {leafSnaps.length}</span>
        {#each valDelta.improved as cat}
            <span class="seg-history-val-delta improved">&minus;{SHORT_LABELS[cat] || cat}</span>
        {/each}
        {#each valDelta.regressed as cat}
            <span class="seg-history-val-delta regression">+{SHORT_LABELS[cat] || cat}</span>
        {/each}
        {#if chainBatchIds.length > 0}
            <button
                class="btn btn-sm seg-history-undo-btn"
                on:click|stopPropagation={handleChainUndoClick}
            >Undo</button>
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
                            splitHL={rootSplitHL}
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
                                splitHL={leafSplitHL(leaf)}
                            />
                        </div>
                    {/each}
                {/if}
            </div>
        </div>
    </div>
</div>
