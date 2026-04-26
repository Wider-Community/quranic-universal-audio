<script lang="ts">
    /**
     * SegmentsList — the <div id="seg-list"> container, Navigation banner, and
     * reactive row rendering via {#each visibleSegs as seg (key)}.
     *
     * Virtualized: only rows in the viewport (plus a buffer) are in the DOM.
     * Large chapters (~1000+ segs) previously rendered every row, so scroll
     * stalled on browser layout/paint of all the canvases + reactive
     * subscriptions per row. We slice the displayed list by scrollTop and a
     * prefix-sum of per-row measured heights (ResizeObserver-fed), inserting
     * spacer divs above/below to keep the scroll container's intrinsic
     * height correct. Row heights are tracked per UID so a single row's
     * height change only reflows rows *after* it — rows above are untouched
     * and never jitter. See ./virtualization.ts for the pure math.
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
    import { editingSegUid } from '../../stores/edit';
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
    import {
        bottomSpacerValue,
        findIdxAtOffset,
        heightForPos,
        rebuildCumHeights,
        topOfRow,
        topSpacerValue,
    } from './virtualization';

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

    // ---- Per-row height cache --------------------------------------------
    // `heights` maps rowKey → measured wrapper height (row + optional silence-
    // gap, as observed on the .seg-row-group wrapper). `cumHeights` is the
    // prefix sum over $displayedSegments: cum[i] = px offset of row i's top.
    // `estimateHeight` is the running mean of measured rows, used as the
    // fallback for rows not yet in the cache (unmeasured off-screen rows).
    // See ./virtualization.ts for the pure math.
    const heights = new Map<string, number>();
    let cumHeights: number[] = [0];
    let estimateHeight = FALLBACK_ROW_HEIGHT;
    let _measuredCount = 0;
    let _measuredSum = 0;

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
            const targetTop = topOfRow(cumHeights, pos);
            const targetH = heightForPos(pos, segs, rowKey, heights, estimateHeight);
            const approx = targetTop + targetH / 2 - viewportHeight / 2;
            // Pick smooth vs. auto up-front based on the configured mode and
            // the distance to the target. Hybrid uses smooth only for jumps
            // longer than a viewport — row-by-row autoplay advances stay
            // instant, while verse-dropdown / Go-to jumps animate.
            const distance = Math.abs(approx - listEl.scrollTop);
            const mode = get(segConfig).scrollAnimMode;
            const behavior: ScrollBehavior =
                mode === SCROLL_ANIM_MODES.SMOOTH ? 'smooth'
                : mode === SCROLL_ANIM_MODES.HYBRID && distance > listEl.clientHeight ? 'smooth'
                : 'auto';
            // Phase 1: instant centering using the prefix-sum offset. The
            // window's startIdx/endIdx derive from scrollTop + cumHeights, so
            // this is exact (not an estimate) for measured rows.
            listEl.scrollTop = Math.max(0, approx);
            scrollTop = listEl.scrollTop;
            // Phase 2: after Svelte renders the new window, defer to the
            // browser's own `scrollIntoView({block: 'center'})` so the
            // browser animates smoothly when the mode asks for it.
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

    // ---- ResizeObserver plumbing -----------------------------------------
    // One observer watches every `.seg-row-group` wrapper (row + optional
    // silence-gap). When a row's measured height differs from its cached
    // value we update `heights`, rebuild `cumHeights`, and — critically —
    // if the row sits ABOVE the current window, compensate `scrollTop` by
    // the delta so visible content doesn't jump (scroll anchoring, same
    // pattern TanStack Virtual / react-window use).
    //
    // A second observer watches the list container so `viewportHeight`
    // refreshes on window resize without needing a scroll event.
    const groupObserver = typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(_handleGroupResize)
        : null;
    const containerObserver = typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(() => {
            if (listEl) viewportHeight = listEl.clientHeight;
        })
        : null;

    function _handleGroupResize(entries: ResizeObserverEntry[]): void {
        if (entries.length === 0) return;
        const segsNow = get(displayedSegments);
        // Snapshot the spacer size the user currently sees so we can anchor
        // it after the rebuild. This covers both cases: a single row's
        // height changed AND `estimateHeight` shifted (which re-prices
        // every unmeasured row above the window).
        const oldTop = topSpacerValue(
            cumHeights, startIdx, editingPos, segsNow, rowKey, heights, estimateHeight,
        );
        let changed = false;
        for (const entry of entries) {
            const el = entry.target as HTMLElement & { __rowKey?: string };
            const key = el.__rowKey;
            if (!key) continue;
            const box = entry.borderBoxSize?.[0];
            const h = box !== undefined ? box.blockSize : entry.contentRect.height;
            if (h <= 0) continue;
            const prev = heights.get(key);
            if (prev !== undefined && Math.abs(prev - h) < 0.5) continue;
            heights.set(key, h);
            if (prev === undefined) {
                _measuredCount++;
                _measuredSum += h;
            } else {
                _measuredSum += h - prev;
            }
            estimateHeight = _measuredCount > 0
                ? _measuredSum / _measuredCount
                : FALLBACK_ROW_HEIGHT;
            changed = true;
        }
        if (!changed) return;
        cumHeights = rebuildCumHeights(segsNow, rowKey, heights, estimateHeight);
        const newTop = topSpacerValue(
            cumHeights, startIdx, editingPos, segsNow, rowKey, heights, estimateHeight,
        );
        const delta = newTop - oldTop;
        if (delta !== 0 && listEl) {
            listEl.scrollTop += delta;
            scrollTop = listEl.scrollTop;
        }
    }

    /** Svelte action: register a row-group wrapper with the observer. The
     *  wrapper carries its rowKey as a non-enumerable property so the
     *  observer callback can look it up without a DOM query. */
    function observeRowGroup(node: HTMLElement, key: string) {
        (node as HTMLElement & { __rowKey?: string }).__rowKey = key;
        groupObserver?.observe(node);
        return {
            update(newKey: string): void {
                (node as HTMLElement & { __rowKey?: string }).__rowKey = newKey;
            },
            destroy(): void {
                groupObserver?.unobserve(node);
            },
        };
    }

    onMount(() => {
        if (listEl) {
            viewportHeight = listEl.clientHeight;
            containerObserver?.observe(listEl);
        }
    });
    onDestroy(() => {
        if (scrollRaf !== null) cancelAnimationFrame(scrollRaf);
        if (_autoScrollRaf !== null) cancelAnimationFrame(_autoScrollRaf);
        groupObserver?.disconnect();
        containerObserver?.disconnect();
    });

    // Apply a deferred scrollTop (set by filter-restore / navigation actions
    // via the pendingScrollTop store) once the DOM has the content laid out.
    afterUpdate(() => {
        const top = get(pendingScrollTop);
        if (top !== null && listEl) {
            listEl.scrollTop = top;
            scrollTop = top;
            pendingScrollTop.set(null);
        }
    });

    // Rebuild the prefix sum whenever the displayed list changes (filter,
    // sort, split, merge, delete, chapter switch). Reads cached heights
    // from `heights`; unmeasured rows fall back to `estimateHeight`. New
    // rows get their real measurement when their wrapper mounts and the
    // ResizeObserver fires — at which point `_handleGroupResize` also
    // rebuilds and anchors the viewport.
    $: {
        void $displayedSegments;
        cumHeights = rebuildCumHeights($displayedSegments, rowKey, heights, estimateHeight);
    }

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
            const targetTop = topOfRow(cumHeights, pos);
            const targetH = heightForPos(pos, $displayedSegments, rowKey, heights, estimateHeight);
            const desired = targetTop + targetH / 2 - viewportHeight / 2;
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
    // Virtualize as long as the list is big enough to benefit. Edit in flight
    // does NOT disable virtualization anymore: previously flipping `editMode`
    // forced every row in the chapter to mount (20k+ DOM nodes, ~2.7s main-
    // thread block on entry in Al-Baqarah). The editing row's transient state
    // (TrimPanel/SplitPanel handle positions on canvas._trimWindow /
    // canvas._splitData) is preserved instead by pinning the editing row into
    // `visibleSegs` even when the viewport scrolls past it (see below).
    $: total = $displayedSegments.length;
    $: virtualize = total > VIRTUALIZE_THRESHOLD;
    // Window slice via binary search on the prefix sum. `findIdxAtOffset`
    // returns the largest i with cum[i] <= y, so scrollTop maps to the row
    // whose top edge is at-or-just-above the viewport top; adding 1 to the
    // lower-viewport-edge result makes endIdx exclusive of the first row
    // fully below the viewport.
    $: startIdx = virtualize
        ? Math.max(0, findIdxAtOffset(cumHeights, scrollTop) - BUFFER_ROWS)
        : 0;
    $: endIdx = virtualize
        ? Math.min(total, findIdxAtOffset(cumHeights, scrollTop + viewportHeight) + 1 + BUFFER_ROWS)
        : total;
    // Position of the row currently being edited within $displayedSegments.
    // Match by UID (stable across split-induced reindexing); -1 when no edit
    // is active or the edited UID isn't in the current filtered view.
    $: editingPos = $editingSegUid !== null
        ? $displayedSegments.findIndex((s) => s.segment_uid === $editingSegUid)
        : -1;
    // Pin the editing row: if it's outside the current window, append it to
    // the slice so its SegmentRow stays mounted (canvas state survives).
    // The pin is a no-op when the editing row is already in the window.
    $: visibleSegs = (() => {
        const base = virtualize ? $displayedSegments.slice(startIdx, endIdx) : $displayedSegments;
        if (editingPos < 0 || (editingPos >= startIdx && editingPos < endIdx)) return base;
        const pinned = $displayedSegments[editingPos];
        return pinned ? [...base, pinned] : base;
    })();
    // Spacers derive from the prefix sum; when the pinned editing row lives
    // outside the window its height is subtracted from the corresponding
    // spacer so it isn't double-counted (the pinned DOM box contributes its
    // own height at the end of the each-block).
    $: topSpacerPx = virtualize
        ? topSpacerValue(cumHeights, startIdx, editingPos, $displayedSegments, rowKey, heights, estimateHeight)
        : 0;
    $: bottomSpacerPx = virtualize
        ? bottomSpacerValue(cumHeights, endIdx, total, editingPos, $displayedSegments, rowKey, heights, estimateHeight)
        : 0;
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
            <!-- .seg-row-group wraps the row + its optional silence-gap so
                 a single ResizeObserver entry covers both; the wrapper is
                 layout-transparent inside .seg-list (see segments.css). -->
            <div class="seg-row-group" use:observeRowGroup={rowKey(seg)}>
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
            </div>
        {/each}
        {#if bottomSpacerPx > 0}
            <div class="seg-list-spacer" style="height: {bottomSpacerPx}px" aria-hidden="true"></div>
        {/if}
    {/if}
</div>
