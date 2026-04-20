<script lang="ts">
    /**
     * SegmentsList — the <div id="seg-list"> container, Navigation banner, and
     * reactive row rendering via {#each visibleSegs as seg (key)}.
     *
     * Virtualized: only rows in the viewport (plus a buffer) are in the DOM.
     * Large chapters (~1000+ segs) previously rendered every row, so scroll
     * stalled on browser layout/paint of all the canvases + reactive
     * subscriptions per row. We now slice the displayed list by scrollTop
     * and measured row height, inserting spacer divs above/below to keep the
     * scroll container's intrinsic height correct.
     *
     * Edit/save/undo flows that mutate `segAllData`'s segments array in place
     * call `applyFiltersAndRender()` which does
     *   activeFilters.update(l => [...l])   // nudge filter subscribers
     *   segAllData.update(a => a)           // notify subscribers
     * triggering the derived `displayedSegments` to re-fire and the {#each}
     * to reconcile. Keyed by `segment_uid` (with chapter:index fallback) so
     * stable rows survive reindexing across split/merge.
     */

    import { afterUpdate, onDestroy, onMount } from 'svelte';
    import { get } from 'svelte/store';

    import { displayedSegments } from '../../stores/filters';
    import { selectedChapter } from '../../stores/chapter';
    import { editMode } from '../../stores/edit';
    import { pendingScrollTop, targetSegmentIndex } from '../../stores/navigation';
    import {
        autoScrollEnabled,
        playingSegmentIndex,
        segListElement,
        waveformContainer,
    } from '../../stores/playback';
    import { segConfig } from '../../stores/config';
    import { segValidation } from '../../stores/validation';
    import { SCROLL_ANIM_MODES } from '../../../../lib/utils/constants';
    import { VIRT_BUFFER_ROWS } from '../../utils/constants';
    import type { Segment } from '../../../../lib/types/domain';
    import Navigation from './Navigation.svelte';
    import SegmentRow from './SegmentRow.svelte';

    export let onRestore: (() => void) | null = null;

    // ---- Virtualization tuning --------------------------------------------
    /** Fallback row height (px, incl. gap) before any row mounts and we can
     *  measure the real thing. Chosen slightly over a typical row so the
     *  initial over-estimate errs on the side of rendering a few extra rows
     *  rather than too few (a gap at the bottom on first paint). */
    const FALLBACK_ROW_HEIGHT = 140;
    /** Extra rows rendered above/below the viewport. Absorbs fast-scroll
     *  bursts so the user rarely sees an unrendered gap. */
    const BUFFER_ROWS = VIRT_BUFFER_ROWS;
    /** Skip virtualization entirely below this count — tiny lists are cheap
     *  to render fully and virtualization adds its own overhead (spacers,
     *  scroll tracking). */
    const VIRTUALIZE_THRESHOLD = 60;

    let listEl: HTMLDivElement | undefined;
    $: segListElement.set(listEl ?? null);

    let scrollTop = 0;
    let viewportHeight = 600;
    let measuredRowHeight = FALLBACK_ROW_HEIGHT;

    let scrollRaf: number | null = null;
    function onScroll(): void {
        // Throttle scrollTop reads to rAF so a burst of scroll events
        // collapses into one reactive update per frame.
        if (scrollRaf !== null) return;
        scrollRaf = requestAnimationFrame(() => {
            scrollRaf = null;
            if (!listEl) return;
            scrollTop = listEl.scrollTop;
            viewportHeight = listEl.clientHeight;
        });
    }

    // ---- Auto-scroll: keep the playing segment centered ------------------
    // Watches $playingSegmentIndex; when Auto-scroll is ON we snap scrollTop
    // so the active row sits at the viewport center. Covers autoplay,
    // manual Play click, and Up/Down arrow nav — all three paths funnel
    // through playFromSegment(), which updates playingSegmentIndex.
    //
    // Direct scrollTop assignment (not scrollIntoView) to sidestep queued
    // smooth-scroll collisions during rapid index changes. rAF throttle
    // coalesces bursts (e.g. ArrowDown spam) into one scroll per frame.
    // The same-index guard (`_lastAutoScrolledIdx`) prevents redundant
    // writes when the highlight loop publishes the same value repeatedly.
    let _autoScrollRaf: number | null = null;
    let _autoScrollTargetIdx = -1;
    let _lastAutoScrolledIdx = -1;

    function _scheduleAutoScroll(idx: number): void {
        _autoScrollTargetIdx = idx;
        if (_autoScrollRaf !== null) return;
        _autoScrollRaf = requestAnimationFrame(() => {
            _autoScrollRaf = null;
            if (!listEl) return;
            const segs = get(displayedSegments);
            const pos = segs.findIndex((s) => s.index === _autoScrollTargetIdx);
            if (pos < 0) return;
            // Pick smooth vs. auto up-front based on the configured mode and
            // the distance to the target. Hybrid uses smooth only for jumps
            // longer than a viewport — row-by-row autoplay advances stay
            // instant, while verse-dropdown / Go-to jumps animate.
            const distance = Math.abs(
                pos * measuredRowHeight - listEl.scrollTop,
            );
            const mode = get(segConfig).scrollAnimMode;
            const behavior: ScrollBehavior =
                mode === SCROLL_ANIM_MODES.SMOOTH ? 'smooth'
                : mode === SCROLL_ANIM_MODES.HYBRID && distance > listEl.clientHeight ? 'smooth'
                : 'auto';
            // Phase 1: approximate centering from measured average row height.
            // Puts the target row close enough that the virtualization window
            // renders it in the next tick. Always instant — phase 2 handles
            // the user-visible animation so smooth-scrolling doesn't race
            // with the virtualization re-slice.
            const approx =
                pos * measuredRowHeight
                - viewportHeight / 2
                + measuredRowHeight / 2;
            listEl.scrollTop = Math.max(0, approx);
            scrollTop = listEl.scrollTop;
            // Phase 2: after Svelte renders the new window, defer to the
            // browser's own `scrollIntoView({block: 'center'})` for exact
            // centering. Our manual math is sensitive to spacer re-measure
            // jitter (the virtualization window recalculates `measuredRow-
            // Height` in afterUpdate, which shifts spacers and thus the
            // perceived row position); letting the browser do it side-
            // steps that loop. Behavior is driven by the scrollAnimMode
            // config (see ScrollAnimMode in stores/playback.ts).
            requestAnimationFrame(() => {
                if (!listEl) return;
                const row = listEl.querySelector<HTMLElement>(
                    `.seg-row[data-seg-index="${_autoScrollTargetIdx}"]`,
                );
                if (!row) return;
                row.scrollIntoView({ block: 'center', behavior });
                scrollTop = listEl.scrollTop;
            });
        });
    }

    // Only auto-scroll when the playing segment belongs to the currently-
    // viewed chapter. Cross-chapter accordion plays (e.g. the validation
    // panel with chapter=null triggers a play from another chapter) must NOT
    // yank the visible list away from what the user is looking at.
    $: if (
        $autoScrollEnabled
        && $playingSegmentIndex
        && $playingSegmentIndex.index !== _lastAutoScrolledIdx
        && ($selectedChapter === '' || $playingSegmentIndex.chapter === parseInt($selectedChapter))
        && listEl
    ) {
        _lastAutoScrolledIdx = $playingSegmentIndex.index;
        _scheduleAutoScroll($playingSegmentIndex.index);
    }

    // Reset the auto-scroll guard on chapter change so re-entering a chapter
    // scrolls on the first playing-index update rather than being skipped as
    // a repeat of the previous chapter's last index.
    $: if ($selectedChapter !== undefined) _lastAutoScrolledIdx = -1;

    onMount(() => {
        if (listEl) viewportHeight = listEl.clientHeight;
    });
    onDestroy(() => {
        if (scrollRaf !== null) cancelAnimationFrame(scrollRaf);
        if (_autoScrollRaf !== null) cancelAnimationFrame(_autoScrollRaf);
    });

    // Re-measure row height after each update so the window math tracks
    // real row sizes (e.g. after font load, accordion state change, zoom).
    // Average across all rendered rows — heights vary wildly per row (a
    // compact row is ~120px; one with validation tags or long Arabic text
    // can exceed 400px), so measuring just the first row causes the
    // spacer math (and therefore total scroll height) to drift whenever
    // the window slides onto a row of atypical height.
    afterUpdate(() => {
        const top = get(pendingScrollTop);
        if (top !== null && listEl) {
            listEl.scrollTop = top;
            scrollTop = top;
            pendingScrollTop.set(null);
        }
        if (listEl) {
            const rows = listEl.querySelectorAll<HTMLElement>('.seg-row');
            if (rows.length > 0) {
                let sum = 0;
                for (const r of rows) sum += r.getBoundingClientRect().height;
                const avg = sum / rows.length + 6; // +gap
                if (avg > 20 && Math.abs(avg - measuredRowHeight) > 4) {
                    measuredRowHeight = avg;
                }
            }
        }
    });

    // When a jump-to-segment request lands, scroll the container so the
    // target row lands in the render window; SegmentRow then reactively
    // fine-tunes with scrollIntoView({block: 'center'}). Without this
    // pre-scroll, a target outside the window never mounts and the
    // reactive scroll never fires.
    //
    // `targetSegmentIndex` now carries {chapter, index}; gate on the
    // chapter matching the currently-viewed one so a cross-chapter jump
    // (that also switched `selectedChapter` before setting the target)
    // doesn't attempt to pre-scroll an index that doesn't exist yet in
    // this list's displayedSegments.
    $: if ($targetSegmentIndex !== null && listEl
        && ($selectedChapter === '' || $targetSegmentIndex.chapter === parseInt($selectedChapter))) {
        const targetIdx = $targetSegmentIndex.index;
        const pos = $displayedSegments.findIndex((s) => s.index === targetIdx);
        if (pos >= 0) {
            const desired = pos * measuredRowHeight - viewportHeight / 2;
            const clamped = Math.max(0, desired);
            if (Math.abs(clamped - scrollTop) > viewportHeight) {
                listEl.scrollTop = clamped;
                scrollTop = clamped;
            }
        }
    }

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

    // ---- Virtualization window -------------------------------------------
    // Disable virtualization for small lists (cheap to render fully) and
    // while an edit is in flight (TrimPanel/SplitPanel hold transient state
    // that must survive; unmounting the editing row mid-drag would lose it).
    $: total = $displayedSegments.length;
    $: virtualize = total > VIRTUALIZE_THRESHOLD && $editMode === null;
    $: startIdx = virtualize
        ? Math.max(0, Math.floor(scrollTop / measuredRowHeight) - BUFFER_ROWS)
        : 0;
    $: endIdx = virtualize
        ? Math.min(total, Math.ceil((scrollTop + viewportHeight) / measuredRowHeight) + BUFFER_ROWS)
        : total;
    $: visibleSegs = virtualize ? $displayedSegments.slice(startIdx, endIdx) : $displayedSegments;
    $: topSpacerPx = virtualize ? startIdx * measuredRowHeight : 0;
    $: bottomSpacerPx = virtualize ? Math.max(0, (total - endIdx) * measuredRowHeight) : 0;
</script>

<div id="seg-list" class="seg-list" bind:this={listEl} use:waveformContainer on:scroll={onScroll}>
    <!-- Navigation banner stays inside #seg-list so `.seg-back-banner`'s
         `position: sticky` scopes to the list's scroll container. -->
    <Navigation on:restore={() => onRestore && onRestore()} />

    {#if total === 0}
        <div class="seg-loading">No segments to display</div>
    {:else}
        {#if topSpacerPx > 0}
            <div class="seg-list-spacer" style="height: {topSpacerPx}px" aria-hidden="true"></div>
        {/if}
        {#each visibleSegs as seg, localIdx (rowKey(seg))}
            <SegmentRow
                {seg}
                {missingWordSegIndices}
                isNeighbour={!!seg._isNeighbour}
                instanceRole="main"
            />
            {#if showSilenceGap(seg, startIdx + localIdx)}
                <div class="seg-silence-gap-wrapper">
                    <div class="seg-silence-gap">
                        &#9208; {Math.round(seg.silence_after_ms ?? 0)}ms
                        (raw: {Math.round(seg.silence_after_raw_ms ?? 0)}ms)
                    </div>
                </div>
            {/if}
        {/each}
        {#if bottomSpacerPx > 0}
            <div class="seg-list-spacer" style="height: {bottomSpacerPx}px" aria-hidden="true"></div>
        {/if}
    {/if}
</div>
