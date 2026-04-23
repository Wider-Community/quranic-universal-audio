<script lang="ts">
    /**
     * StatsChart — a single Chart.js histogram card.
     *
     * Props:
     *  - title: human-readable label
     *  - dist: {bins, counts, percentiles?} distribution data
     *  - cfg: chart configuration (colors, format, refLine, etc.)
     *  - reciter: currently-loaded reciter slug (for save-chart API)
     *
     * Chart lifecycle: full destroy+rebuild on data change.
     * onDestroy cleans up the Chart instance.
     */
    import { onDestroy } from 'svelte';

    import { fetchJson } from '../../../../lib/api';
    import { drawBarChart } from '../../utils/stats-chart-draw';
    import type { SegSaveChartResponse } from '../../../../lib/types/api';
    import type { ChartCfg, Distribution } from '../../types/stats';

    import type { Chart } from '../../../../lib/utils/chart';

    export let title: string;
    export let dist: Distribution;
    export let cfg: ChartCfg;
    export let reciter: string;

    /** Whether this chart is open in fullscreen (drives ChartFullscreen). */
    export let onOpenFullscreen: ((dist: Distribution, cfg: ChartCfg) => void) | null = null;

    let canvasEl: HTMLCanvasElement | null = null;
    let chartInstance: Chart | null = null;
    let showSavedTip = false;

    // ---------------------------------------------------------------------------
    // Build chart whenever canvas is available and dist data changes.
    // ---------------------------------------------------------------------------

    function buildChart(): void {
        if (!canvasEl) return;
        if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
        chartInstance = drawBarChart(canvasEl, dist, cfg) ?? null;
    }

    // Rebuild when canvas binds (mount) and on every dist/cfg change. The
    // reactive statement runs once during initial render after `bind:this`
    // populates `canvasEl`, so a separate `onMount(buildChart)` would
    // double-fire (build → destroy → rebuild). Reactive-only is sufficient.
    $: if (canvasEl && dist) { buildChart(); }

    onDestroy(() => {
        if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
    });

    // ---------------------------------------------------------------------------
    // Save chart PNG to server.
    // ---------------------------------------------------------------------------

    let savedTipTimer: ReturnType<typeof setTimeout> | null = null;
    function flashSavedTip(): void {
        showSavedTip = true;
        if (savedTipTimer !== null) clearTimeout(savedTipTimer);
        savedTipTimer = setTimeout(() => { showSavedTip = false; savedTipTimer = null; }, 1200);
    }

    function handleSave(): void {
        if (!canvasEl || !reciter) return;
        canvasEl.toBlob((blob) => {
            if (!blob) return;
            const fd = new FormData();
            fd.append('name', cfg.key);
            fd.append('image', blob, cfg.key + '.png');
            fetchJson<SegSaveChartResponse>(
                `/api/seg/stats/${encodeURIComponent(reciter)}/save-chart`,
                { method: 'POST', body: fd },
            ).then((data) => {
                if (data.ok) flashSavedTip();
            }).catch((err: unknown) => { console.warn('Stats save failed:', err); });
        }, 'image/png');
    }
</script>

<div class="seg-stats-chart-wrap">
    {#if showSavedTip}<span class="seg-stats-saved-tip">Saved</span>{/if}
    <div class="seg-stats-chart-header">
        <h4>{title}</h4>
        <span class="seg-stats-chart-btns">
            {#if onOpenFullscreen}
                <button
                    class="seg-stats-chart-btn"
                    title="Full screen"
                    on:click={() => onOpenFullscreen && onOpenFullscreen(dist, cfg)}
                >&#x26F6;</button>
            {/if}
            <button class="seg-stats-chart-btn" title="Save PNG" on:click={handleSave}>&#x2B73;</button>
        </span>
    </div>
    <div style="position: relative; width: 100%; height: 160px;">
        <canvas bind:this={canvasEl}></canvas>
    </div>
</div>
