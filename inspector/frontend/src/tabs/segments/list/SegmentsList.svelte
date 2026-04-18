<script lang="ts">
    /**
     * SegmentsList — the <div id="seg-list"> container, Navigation banner, and
     * reactive row rendering via {#each $displayedSegments as seg (key)}.
     *
     * Edit/save/undo flows that mutate `segAllData`'s segments array in place
     * call `applyFiltersAndRender()` which does
     *   activeFilters.update(l => [...l])   // nudge filter subscribers
     *   segAllData.update(a => a)           // notify subscribers
     * triggering the derived `displayedSegments` to re-fire and the {#each}
     * to reconcile. Keyed by `segment_uid` (with chapter:index fallback) so
     * stable rows survive reindexing across split/merge.
     */

    import { afterUpdate } from 'svelte';
    import { get } from 'svelte/store';

    import { displayedSegments } from '../../../lib/stores/segments/filters';
    import { selectedChapter } from '../../../lib/stores/segments/chapter';
    import { pendingScrollTop } from '../../../lib/stores/segments/navigation';
    import { segListElement, waveformContainer } from '../../../lib/stores/segments/playback';
    import { segValidation } from '../../../lib/stores/segments/validation';
    import type { Segment } from '../../../lib/types/domain';
    import Navigation from './Navigation.svelte';
    import SegmentRow from './SegmentRow.svelte';

    export let onRestore: (() => void) | null = null;

    let listEl: HTMLDivElement | undefined;
    $: segListElement.set(listEl ?? null);

    // Consume one-shot pendingScrollTop after the {#each} reconciles. Called
    // from _restoreFilterView — the scroll must happen once rows are in the
    // DOM so scrollTop lands at the saved offset.
    afterUpdate(() => {
        const top = get(pendingScrollTop);
        if (top !== null && listEl) {
            listEl.scrollTop = top;
            pendingScrollTop.set(null);
        }
    });

    /** Missing-word seg-indices for the current chapter. Memoized: the Set is
     *  expensive to pass-by-value — new identity marks every <SegmentRow>
     *  dirty (O(N) reactive work per confirm at N≈1000 segs). Cache by
     *  reference on ($segValidation, $selectedChapter); return the SAME Set
     *  when neither dependency changed. */
    let _missingCache: Set<number> = new Set();
    let _missingCacheValRef: typeof $segValidation = null;
    let _missingCacheChapter = '';
    $: missingWordSegIndices = (() => {
        if ($segValidation === _missingCacheValRef && $selectedChapter === _missingCacheChapter) {
            return _missingCache;
        }
        _missingCacheValRef = $segValidation;
        _missingCacheChapter = $selectedChapter;
        const set = new Set<number>();
        if (!$segValidation || !$segValidation.missing_words) { _missingCache = set; return set; }
        const chapter = parseInt($selectedChapter) || 0;
        if (!chapter) { _missingCache = set; return set; }
        for (const mw of $segValidation.missing_words) {
            if (mw.chapter === chapter && mw.seg_indices) {
                for (const idx of mw.seg_indices) set.add(idx);
            }
        }
        _missingCache = set;
        return set;
    })();

    /** Stable key for {#each} reconciliation. UID survives split-induced
     *  index reshuffles; fallback compound key is unique within a chapter. */
    function rowKey(s: Segment): string {
        return s.segment_uid ?? `${s.chapter ?? ''}:${s.index}`;
    }

    /** Whether to render a silence-gap wrapper between `seg` and the next
     *  segment — only when the next-displayed is the consecutive index. */
    function showSilenceGap(seg: Segment, displayIdx: number): boolean {
        if (seg.silence_after_ms == null) return false;
        const nextDisplayed = $displayedSegments[displayIdx + 1];
        return !!nextDisplayed && nextDisplayed.index === seg.index + 1;
    }
</script>

<div id="seg-list" class="seg-list" bind:this={listEl} use:waveformContainer>
    <!-- Navigation banner stays inside #seg-list so `.seg-back-banner`'s
         `position: sticky` scopes to the list's scroll container. -->
    <Navigation on:restore={() => onRestore && onRestore()} />

    {#if $displayedSegments.length === 0}
        <div class="seg-loading">No segments to display</div>
    {:else}
        {#each $displayedSegments as seg, displayIdx (rowKey(seg))}
            <SegmentRow
                {seg}
                {missingWordSegIndices}
                isNeighbour={!!seg._isNeighbour}
            />
            {#if showSilenceGap(seg, displayIdx)}
                <div class="seg-silence-gap-wrapper">
                    <div class="seg-silence-gap">
                        &#9208; {Math.round(seg.silence_after_ms ?? 0)}ms
                        (raw: {Math.round(seg.silence_after_raw_ms ?? 0)}ms)
                    </div>
                </div>
            {/if}
        {/each}
    {/if}
</div>
