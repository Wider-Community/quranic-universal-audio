<script lang="ts">
    /**
     * SegmentsList — the <div id="seg-list"> container, Navigation banner, and
     * Svelte-driven row rendering via {#each}.
     *
     * Wave 7 adopted: replaces the Wave-5 imperative `renderSegList` bridge.
     * Rows render via {#each $displayedSegments as seg (key)} → <SegmentRow>.
     * Silence-gap markers are inlined; missing-word tags are computed from
     * `state.segValidation` reactively (no observer post-walk needed —
     * SegmentRow.onMount registers each canvas with the IntersectionObserver
     * directly).
     *
     * Edit/save/undo flows that mutate state.segAllData.segments in place call
     * `applyFiltersAndRender()` (now a shim — segments/filters.ts) which does
     *   activeFilters.set([...state.segActiveFilters])  // sync state → store
     *   segAllData.update(a => a)                       // notify subscribers
     * triggering the derived `displayedSegments` to re-fire and the {#each}
     * to reconcile. Keyed by `segment_uid` (with chapter:index fallback) so
     * stable rows survive reindexing across split/merge.
     *
     * Banner: `.seg-back-banner` lives inside #seg-list (Navigation.svelte
     * renders before {#each}) so its `position: sticky` scopes correctly to
     * the list scroll container. Banner-preservation walk that Wave-5
     * imperative `renderSegList` did is no longer needed — the banner is
     * Svelte-owned and outside the {#each} block.
     */

    import { displayedSegments } from '../../lib/stores/segments/filters';
    import { selectedChapter } from '../../lib/stores/segments/chapter';
    import { state } from '../../segments/state';
    import type { Segment } from '../../types/domain';
    import Navigation from './Navigation.svelte';
    import SegmentRow from './SegmentRow.svelte';

    export let onRestore: (() => void) | null = null;

    /** Compute missing-word seg-indices for the current chapter from
     *  state.segValidation. `state.segValidation` is not a store, so we
     *  trigger re-derivation on every $displayedSegments change — which
     *  fires after save+revalidate (applyFiltersAndRender → segAllData.update).
     *  Without this, missing-word tags would go stale after save until the
     *  user changes chapters. */
    $: missingWordSegIndices = (() => {
        void $displayedSegments; // dependency: re-derive on list refresh
        const set = new Set<number>();
        if (!state.segValidation || !state.segValidation.missing_words) return set;
        const chapter = parseInt($selectedChapter) || 0;
        if (!chapter) return set;
        for (const mw of state.segValidation.missing_words) {
            if (mw.chapter === chapter && mw.seg_indices) {
                for (const idx of mw.seg_indices) set.add(idx);
            }
        }
        return set;
    })();

    /** Stable key for {#each} reconciliation. UID survives split-induced
     *  index reshuffles; fallback compound key is unique within a chapter. */
    function rowKey(s: Segment): string {
        return s.segment_uid ?? `${s.chapter ?? ''}:${s.index}`;
    }

    /** Whether to render a silence-gap wrapper between `seg` and the next
     *  segment in the displayed list. Mirrors Stage-1 renderSegList logic
     *  (only show when next-displayed is the consecutive index). */
    function showSilenceGap(seg: Segment, displayIdx: number): boolean {
        if (seg.silence_after_ms == null) return false;
        const nextDisplayed = $displayedSegments[displayIdx + 1];
        return !!nextDisplayed && nextDisplayed.index === seg.index + 1;
    }
</script>

<div id="seg-list" class="seg-list">
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
