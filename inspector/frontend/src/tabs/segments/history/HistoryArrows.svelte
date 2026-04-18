<script lang="ts">
    /**
     * HistoryArrows — declarative SVG arrow column for one edit-history diff.
     *
     * Accepts arrays of before/after card element refs (plus optional
     * delete-placeholder ref) as props, measures them via
     * `getBoundingClientRect()` inside `afterUpdate`, pipes numeric Y
     * positions into the pure `computeArrowLayout` helper from
     * `lib/utils/svg-arrow-geometry.ts`, and renders `<svg>` + inline
     * `<defs>/<marker>` + `{#each paths}` + optional red-X `<g>` entirely
     * via markup.
     *
     * `<defs>` is inline per instance — a handful of extra `<marker>` nodes
     * on-screen are cheaper than a global-singleton lifecycle. The marker id
     * is per-instance (`hist-arrow-{uid}`) so multiple arrows in a single
     * chain row do not share marker identity.
     */

    import { afterUpdate, onMount, tick } from 'svelte';

    import {
        computeArrowLayout,
        type ArrowLayout,
        type ArrowPath,
        type XMark,
    } from '../../../lib/utils/svg-arrow-geometry';

    // Props ------------------------------------------------------------------

    /** Before-card HTML elements whose vertical center is the arrow start. */
    export let beforeCards: HTMLElement[] = [];
    /** After-card HTML elements whose vertical center is the arrow end. */
    export let afterCards: HTMLElement[] = [];
    /**
     * Optional empty-placeholder element (shown when all "after" cards are
     * absent — e.g. delete op). When present AND afterCards is empty, arrows
     * aim at this element and a red X is drawn at its center.
     */
    export let emptyEl: HTMLElement | null = null;

    // Internal state ---------------------------------------------------------

    let svgEl: SVGSVGElement | undefined;
    let height = 1;
    let layout: ArrowLayout = { paths: [], xMark: null };
    let paths: ArrowPath[] = [];
    let xMark: XMark | null = null;
    /** Per-instance marker id so multiple diffs in one batch don't collide. */
    const markerId = `hist-arrow-${Math.random().toString(36).slice(2, 10)}`;

    // Geometry ---------------------------------------------------------------

    function measure(): void {
        if (!svgEl) return;
        const arrowCol = svgEl.parentElement;
        if (!arrowCol) return;
        const colRect = arrowCol.getBoundingClientRect();
        if (colRect.height < 1) return;

        const midYs = (cards: HTMLElement[]): number[] =>
            cards.map((c) => {
                const r = c.getBoundingClientRect();
                return r.top + r.height / 2 - colRect.top;
            });
        const bY = midYs(beforeCards);
        const aY = afterCards.length > 0 ? midYs(afterCards) : [];
        let eY: number | null = null;
        if (afterCards.length === 0 && emptyEl) {
            const er = emptyEl.getBoundingClientRect();
            eY = er.top + er.height / 2 - colRect.top;
        }

        layout = computeArrowLayout({ beforeYs: bY, afterYs: aY, emptyY: eY });
        paths = layout.paths;
        xMark = layout.xMark;
        height = colRect.height;
    }

    afterUpdate(measure);
    onMount(() => {
        // First measurement also runs via afterUpdate; schedule once more
        // after the browser has settled layout (images, late fonts, etc.).
        void tick().then(measure);
    });
</script>

<svg
    bind:this={svgEl}
    height={height}
    viewBox={`0 0 60 ${height}`}
    xmlns="http://www.w3.org/2000/svg"
>
    <defs>
        <marker
            id={markerId}
            viewBox="0 0 10 7"
            refX="10"
            refY="3.5"
            markerWidth="8"
            markerHeight="6"
            orient="auto-start-reverse"
        >
            <polygon points="0 0, 10 3.5, 0 7" fill="#4cc9f0" />
        </marker>
    </defs>
    {#each paths as p}
        <path
            d={p.d}
            fill="none"
            stroke="#4cc9f0"
            stroke-width="1.5"
            stroke-dasharray={p.dashed ? '4,3' : undefined}
            marker-end={`url(#${markerId})`}
        />
    {/each}
    {#if xMark}
        <g stroke="#f44336" stroke-width="2">
            <line
                x1={xMark.cx - xMark.size}
                y1={xMark.cy - xMark.size}
                x2={xMark.cx + xMark.size}
                y2={xMark.cy + xMark.size}
            />
            <line
                x1={xMark.cx - xMark.size}
                y1={xMark.cy + xMark.size}
                x2={xMark.cx + xMark.size}
                y2={xMark.cy - xMark.size}
            />
        </g>
    {/if}
</svg>
