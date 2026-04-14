<script lang="ts">
    /**
     * SegmentsList — renders the filtered segments as <SegmentRow> rows with
     * silence-gap markers between same-entry consecutive segments.
     *
     * Post-mount, attaches the IntersectionObserver to each newly-visible
     * canvas[data-needs-waveform] so the waveform draw kicks in when the row
     * scrolls into view. The observer itself lives in segments/waveform/index
     * (Wave-6 owns the rewrite); this component just invokes
     * _ensureWaveformObserver + walks the rendered DOM after every render.
     *
     * Playback highlight (`.playing` / `.reached` / `.past` classes) stays
     * imperative — Wave-6 playback code sets these via classList on rows
     * queried by data-seg-index. That's the "hybrid 60fps" pattern from the
     * Wave-4 handoff: structure via {#each}, per-frame mutations imperative.
     *
     * The top of the list renders the Navigation back-banner when applicable;
     * that component is imported here rather than at SegmentsTab because the
     * banner's Stage-1 position was inserted as the first child of #seg-list.
     */

    import { afterUpdate, onMount } from 'svelte';

    import type { Segment } from '../../types/domain';
    import {
        currentChapterSegments,
        segAllData,
        selectedChapter,
    } from '../../lib/stores/segments/chapter';
    import { displayedSegments } from '../../lib/stores/segments/filters';
    import { state } from '../../segments/state';
    import { _ensureWaveformObserver } from '../../segments/waveform/index';
    import Navigation from './Navigation.svelte';
    import SegmentRow from './SegmentRow.svelte';

    export let onRestore: (() => void) | null = null;

    let listEl: HTMLDivElement | undefined;

    // Missing-word segment indices for the current chapter — read from
    // state.segValidation (Wave-8-owned). Computed inline via $: to match
    // Stage-1 behaviour.
    let missingWordSegIndices: Set<number> = new Set();
    $: {
        const _chStr = $selectedChapter;
        const chapter = _chStr ? parseInt(_chStr) : 0;
        const val = state.segValidation;
        const next = new Set<number>();
        if (val && val.missing_words) {
            for (const mw of val.missing_words) {
                if (mw.chapter === chapter && mw.seg_indices) {
                    mw.seg_indices.forEach((idx) => next.add(idx));
                }
            }
        }
        missingWordSegIndices = next;
    }

    // Silence-gap markers — emit a gap between two displayed segments if they
    // are consecutive in the chapter (same entry, index+1) with a computed
    // silence_after_ms on the first.
    interface RowItem {
        kind: 'row';
        seg: Segment;
    }
    interface GapItem {
        kind: 'gap';
        afterIndex: number;
        ms: number;
        rawMs: number;
    }
    type ListItem = RowItem | GapItem;

    $: items = (() => {
        const segs = $displayedSegments;
        const out: ListItem[] = [];
        segs.forEach((seg, i) => {
            out.push({ kind: 'row', seg });
            const next = segs[i + 1];
            if (seg.silence_after_ms != null && next && next.index === seg.index + 1) {
                out.push({
                    kind: 'gap',
                    afterIndex: seg.index,
                    ms: Math.round(seg.silence_after_ms),
                    rawMs: Math.round(seg.silence_after_raw_ms ?? 0),
                });
            }
        });
        return out;
    })();

    // Placeholder messages mirror Stage-1 behaviour exactly.
    $: hasChapter = !!$selectedChapter;
    $: hasData = $segAllData !== null;
    $: showEmptyPlaceholder =
        hasData && !hasChapter && $displayedSegments.length === 0;
    $: showNoSegmentsMessage =
        hasData && hasChapter && $currentChapterSegments.length > 0 && $displayedSegments.length === 0;
    $: showNoChapterSegments =
        hasData && hasChapter && $currentChapterSegments.length === 0;

    afterUpdate(() => {
        // Attach observer to newly-rendered canvases — harmless if a canvas
        // is already observed (the observer dedupes internally).
        if (!listEl) return;
        // Reset playback highlight tracking so playback code picks up fresh
        // references on the next frame.
        state._prevHighlightedRow = null;
        state._prevHighlightedIdx = -1;
        state._currentPlayheadRow = null;
        state._prevPlayheadIdx = -1;
        try {
            const observer = _ensureWaveformObserver();
            listEl
                .querySelectorAll<HTMLCanvasElement>('canvas[data-needs-waveform]')
                .forEach((c) => observer.observe(c));
        } catch {
            // Observer init may fail in tests or if dependencies not ready.
        }
    });

    onMount(() => {
        // Expose the list container to imperative code that still reads
        // state.dom.segListEl (Wave 6+ playback, keyboard navigation,
        // scroll-to-segment). The SegmentsTab-level bridge mirrors this
        // via a similar assignment; duplicated here for safety.
        if (listEl) {
            // state.dom.segListEl is already set from the tab shell's DOMContentLoaded.
            // Nothing to do — consumers query by id `seg-list`.
        }
    });
</script>

<div id="seg-list" class="seg-list" bind:this={listEl}>
    <Navigation on:restore={() => onRestore && onRestore()} />

    {#if showEmptyPlaceholder || showNoChapterSegments}
        <div class="seg-loading">Select a chapter or add a filter to view segments</div>
    {:else if showNoSegmentsMessage}
        <div class="seg-loading">No segments to display</div>
    {:else}
        {#each items as item (item.kind === 'row'
            ? `row-${item.seg.chapter}-${item.seg.index}`
            : `gap-${item.afterIndex}`)}
            {#if item.kind === 'row'}
                <SegmentRow
                    seg={item.seg}
                    isNeighbour={item.seg._isNeighbour === true}
                    {missingWordSegIndices}
                />
            {:else}
                <div class="seg-silence-gap-wrapper">
                    <div class="seg-silence-gap">
                        &#9208; {item.ms}ms (raw: {item.rawMs}ms)
                    </div>
                </div>
            {/if}
        {/each}
    {/if}
</div>
