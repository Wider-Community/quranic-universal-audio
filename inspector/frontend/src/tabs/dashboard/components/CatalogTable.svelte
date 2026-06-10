<script context="module" lang="ts">
    import type { PublicDelivery, PublicReciter } from '../../../lib/types/public-state';

    export interface RowEntry {
        reciter: PublicReciter;
        visibleDeliveries: PublicDelivery[];
    }
</script>

<script lang="ts">
    /**
     * Catalog list — one row per reciter that has at least one combination
     * passing the active filters. Counts on each row reflect that post-filter
     * subset.
     *
     * Virtualized: only the rows in (and just around) the viewport are mounted,
     * so the multi-thousand-row roster renders and re-filters smoothly instead
     * of reconciling every ReciterRow on each change. The scroll container is
     * this component's root; the parent (`CatalogList`) gives it a bounded
     * height. Window math is the shared prefix-sum helper in
     * `lib/utils/list-virtualization` (also used by the Segments list).
     */
    import { createEventDispatcher, onDestroy, onMount } from 'svelte';

    import ReciterRow from '../../../lib/components/ReciterRow.svelte';
    import {
        bottomSpacerValue,
        findIdxAtOffset,
        rebuildCumHeights,
        topSpacerValue,
    } from '../../../lib/utils/list-virtualization';

    export let rows: RowEntry[];
    /** Bumped by the parent whenever the search/filter/sort inputs change, so a
     *  freshly narrowed list opens at the top instead of a stale scroll offset. */
    export let resetKey = '';

    const dispatch = createEventDispatcher<{
        open: PublicReciter;
        play: RowEntry;
    }>();

    function isPlayable(d: PublicDelivery): boolean {
        return d.audio_category !== 'by_ayah';
    }

    // ---- Virtualization ---------------------------------------------------
    /** Fallback row height (px) before any row mounts and we measure the real
     *  thing. A touch over a typical row so the first paint over-renders rather
     *  than leaving a gap. */
    const FALLBACK_ROW_HEIGHT = 64;
    /** Rows rendered above/below the viewport to absorb fast-scroll bursts. */
    const BUFFER_ROWS = 12;
    /** Skip virtualization below this count — small lists are cheap to render
     *  whole and the spacer/observer overhead isn't worth it. */
    const VIRTUALIZE_THRESHOLD = 60;

    let listEl: HTMLDivElement | undefined;
    let scrollTop = 0;
    let viewportHeight = 600;

    // `heights` maps rowKey → measured wrapper height; `cumHeights` is the
    // prefix sum (cum[i] = px offset of row i's top); `estimateHeight` is the
    // running mean used for not-yet-measured rows. See list-virtualization.ts.
    const heights = new Map<string, number>();
    let cumHeights: number[] = [0];
    let estimateHeight = FALLBACK_ROW_HEIGHT;
    let _measuredCount = 0;
    let _measuredSum = 0;

    const rowKey = (row: RowEntry): string => row.reciter.reciter_id;

    let scrollRaf: number | null = null;
    function onScroll(): void {
        if (scrollRaf !== null) return;
        scrollRaf = requestAnimationFrame(() => {
            scrollRaf = null;
            if (!listEl) return;
            scrollTop = listEl.scrollTop;
            viewportHeight = listEl.clientHeight;
        });
    }

    // One observer watches each row wrapper; a second keeps `viewportHeight`
    // fresh on container resize. On a height change we rebuild the prefix sum
    // and, if the row sits above the window, compensate scrollTop so visible
    // content doesn't jump (scroll anchoring).
    const rowObserver = typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(_handleRowResize)
        : null;
    const containerObserver = typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(() => { if (listEl) viewportHeight = listEl.clientHeight; })
        : null;

    function _handleRowResize(entries: ResizeObserverEntry[]): void {
        if (entries.length === 0) return;
        const oldTop = topSpacerValue(cumHeights, startIdx, -1, rows, rowKey, heights, estimateHeight);
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
            if (prev === undefined) { _measuredCount++; _measuredSum += h; }
            else { _measuredSum += h - prev; }
            estimateHeight = _measuredCount > 0 ? _measuredSum / _measuredCount : FALLBACK_ROW_HEIGHT;
            changed = true;
        }
        if (!changed) return;
        cumHeights = rebuildCumHeights(rows, rowKey, heights, estimateHeight);
        const newTop = topSpacerValue(cumHeights, startIdx, -1, rows, rowKey, heights, estimateHeight);
        const delta = newTop - oldTop;
        if (delta !== 0 && listEl) {
            listEl.scrollTop += delta;
            scrollTop = listEl.scrollTop;
        }
    }

    /** Svelte action: register a row wrapper with the observer. The wrapper
     *  carries its rowKey as a property so the callback can look it up. */
    function observeRow(node: HTMLElement, key: string) {
        (node as HTMLElement & { __rowKey?: string }).__rowKey = key;
        rowObserver?.observe(node);
        return {
            update(newKey: string): void {
                (node as HTMLElement & { __rowKey?: string }).__rowKey = newKey;
            },
            destroy(): void { rowObserver?.unobserve(node); },
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
        rowObserver?.disconnect();
        containerObserver?.disconnect();
    });

    // Rebuild the prefix sum whenever the row set changes (filter, sort, poll).
    $: { void rows; cumHeights = rebuildCumHeights(rows, rowKey, heights, estimateHeight); }

    // A new search/filter/sort narrows the list — snap back to the top.
    let _prevResetKey = resetKey;
    $: if (resetKey !== _prevResetKey) {
        _prevResetKey = resetKey;
        scrollTop = 0;
        if (listEl) listEl.scrollTop = 0;
    }

    $: total = rows.length;
    $: virtualize = total > VIRTUALIZE_THRESHOLD;
    $: startIdx = virtualize
        ? Math.max(0, findIdxAtOffset(cumHeights, scrollTop) - BUFFER_ROWS)
        : 0;
    $: endIdx = virtualize
        ? Math.min(total, findIdxAtOffset(cumHeights, scrollTop + viewportHeight) + 1 + BUFFER_ROWS)
        : total;
    $: visibleRows = virtualize ? rows.slice(startIdx, endIdx) : rows;
    $: topSpacerPx = virtualize
        ? topSpacerValue(cumHeights, startIdx, -1, rows, rowKey, heights, estimateHeight)
        : 0;
    $: bottomSpacerPx = virtualize
        ? bottomSpacerValue(cumHeights, endIdx, total, -1, rows, rowKey, heights, estimateHeight)
        : 0;
</script>

{#if rows.length === 0}
    <div class="empty">
        <p>No reciters match the current filters.</p>
    </div>
{:else}
    <div class="catalog" bind:this={listEl} on:scroll={onScroll}>
        {#if topSpacerPx > 0}
            <div class="cat-spacer" style="height: {topSpacerPx}px" aria-hidden="true"></div>
        {/if}
        {#each visibleRows as row (row.reciter.reciter_id)}
            <div class="cat-row-group" use:observeRow={rowKey(row)}>
                <ReciterRow
                    reciter={row.reciter}
                    visibleDeliveries={row.visibleDeliveries}
                    showPlay={row.visibleDeliveries.some(isPlayable)}
                    on:click={() => dispatch('open', row.reciter)}
                    on:play={() => dispatch('play', row)}
                />
            </div>
        {/each}
        {#if bottomSpacerPx > 0}
            <div class="cat-spacer" style="height: {bottomSpacerPx}px" aria-hidden="true"></div>
        {/if}
    </div>
{/if}

<style>
    .catalog {
        margin-top: var(--s-2);
        border-top: 1px solid var(--border-quiet);
        overflow-y: auto;
        /* Filled by the parent's shared-height layout; falls back to natural
           flow if no height envelope is set (e.g. narrow single-column). */
        flex: 1 1 auto;
        min-height: 0;
    }
    .cat-spacer { flex: 0 0 auto; }
    @media (max-width: 900px) {
        /* Single column: the parent's height envelope is dropped, so anchor the
           list to a viewport-tall scroll box — keeps virtualization alive. */
        .catalog { height: calc(100dvh - 220px); flex: none; }
    }
    .empty {
        padding: var(--s-12) var(--gutter);
        text-align: center;
        color: var(--text-muted);
        font-size: var(--fs-meta);
    }
</style>
