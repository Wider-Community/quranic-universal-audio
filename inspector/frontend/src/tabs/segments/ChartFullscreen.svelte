<script lang="ts">
    /**
     * ChartFullscreen — fullscreen overlay for a single histogram chart.
     *
     * Props:
     *  - dist: distribution data (null = overlay hidden)
     *  - cfg: chart configuration
     *  - reciter: currently-loaded reciter slug (for save-chart API)
     *  - onClose: called when user closes the overlay
     *
     * Escape or backdrop click closes the overlay.
     * A separate Chart.js instance is used (not the inline card canvas).
     */
    import { onDestroy } from 'svelte';

    import { fetchJson } from '../../lib/api';
    import { drawBarChart } from '../../lib/utils/stats-chart-draw';
    import type { SegSaveChartResponse } from '../../lib/types/api';
    import type { ChartCfg, Distribution } from './stats-types';

    import type { Chart } from '../../lib/utils/chart';

    export let dist: Distribution | null = null;
    export let cfg: ChartCfg | null = null;
    export let reciter: string = '';
    export let onClose: () => void = () => { /* noop */ };

    let canvasEl: HTMLCanvasElement | null = null;
    let chartInstance: Chart | null = null;
    let showSavedTip = false;

    // Rebuild chart whenever the overlay is shown (dist+cfg become non-null)
    // or canvas ref is ready.
    $: if (canvasEl && dist && cfg) {
        rebuildChart(canvasEl, dist, cfg);
    }

    // When dist/cfg go null, destroy any existing chart.
    $: if (!dist || !cfg) {
        if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
    }

    onDestroy(() => {
        if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
    });

    function rebuildChart(canvas: HTMLCanvasElement, d: Distribution, c: ChartCfg): void {
        if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
        // Defer one frame so the canvas has its layout dimensions.
        requestAnimationFrame(() => {
            chartInstance = drawBarChart(canvas, d, c) ?? null;
        });
    }

    function handleBackdropClick(e: MouseEvent): void {
        if (e.target === e.currentTarget) onClose();
    }

    function handleKeydown(e: KeyboardEvent): void {
        if (e.key === 'Escape') onClose();
    }

    function flashSavedTip(): void {
        showSavedTip = true;
        setTimeout(() => { showSavedTip = false; }, 1200);
    }

    function handleSave(): void {
        if (!canvasEl || !reciter || !cfg) return;
        canvasEl.toBlob((blob) => {
            if (!blob || !cfg) return;
            const fd = new FormData();
            fd.append('name', cfg.key);
            fd.append('image', blob, cfg.key + '.png');
            fetchJson<SegSaveChartResponse>(
                `/api/seg/stats/${encodeURIComponent(reciter)}/save-chart`,
                { method: 'POST', body: fd },
            ).then((data) => {
                if (data.ok) flashSavedTip();
            });
        }, 'image/png');
    }
</script>

<svelte:window on:keydown={handleKeydown} />

{#if dist && cfg}
    <!-- svelte-ignore a11y-click-events-have-key-events -->
    <!-- svelte-ignore a11y-no-static-element-interactions -->
    <div
        id="seg-stats-fullscreen"
        class="seg-stats-fullscreen"
        on:click={handleBackdropClick}
    >
        {#if showSavedTip}<span class="seg-stats-saved-tip">Saved</span>{/if}
        <div class="seg-stats-fs-inner">
            <div class="seg-stats-fs-bar">
                <span class="seg-stats-fs-title">{cfg.title}</span>
                <button class="seg-stats-chart-btn seg-stats-fs-save" title="Save PNG" on:click={handleSave}>&#x2B73;</button>
                <button class="seg-stats-chart-btn seg-stats-fs-close" title="Close" on:click={onClose}>&#x2715;</button>
            </div>
            <div style="flex: 1; min-height: 0; position: relative;">
                <canvas bind:this={canvasEl}></canvas>
            </div>
        </div>
    </div>
{/if}

<style>
    .seg-stats-fullscreen {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.7);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1000;
    }
    .seg-stats-fs-inner {
        background: #16213e;
        border: 1px solid #2a2a4a;
        border-radius: 8px;
        width: 90vw;
        max-width: 900px;
        height: 70vh;
        display: flex;
        flex-direction: column;
        padding: 12px;
    }
    .seg-stats-fs-bar {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;
    }
    .seg-stats-fs-title {
        flex: 1;
        font-size: 0.95rem;
        font-weight: 600;
        color: #e0e0e0;
    }
</style>
