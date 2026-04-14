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
    import { Chart } from '../../lib/utils/chart';
    import type { SegSaveChartResponse } from '../../types/api';
    import type { ChartCfg, Distribution } from './stats-types';

    import type { ChartConfiguration, TooltipItem } from 'chart.js';

    export let dist: Distribution | null = null;
    export let cfg: ChartCfg | null = null;
    export let reciter: string = '';
    export let onClose: () => void = () => { /* noop */ };

    let canvasEl: HTMLCanvasElement | null = null;
    let chartInstance: Chart | null = null;

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
                if (data.ok) {
                    const tip = document.createElement('span');
                    tip.className = 'seg-stats-saved-tip';
                    tip.textContent = 'Saved';
                    document.body.appendChild(tip);
                    setTimeout(() => tip.remove(), 1200);
                }
            });
        }, 'image/png');
    }

    // ---------------------------------------------------------------------------
    // _findBinIndex — locate a value within distribution bins
    // ---------------------------------------------------------------------------

    function _findBinIndex(bins: number[], value: number): number {
        if (bins.length < 2) return 0;
        const binStep = (bins[1] ?? 0) - (bins[0] ?? 0);
        if (binStep === 0) return 0;
        return Math.max(-0.5, Math.min(bins.length - 0.5, (value - (bins[0] ?? 0)) / binStep));
    }

    // ---------------------------------------------------------------------------
    // drawBarChart — same as StatsChart, for the fullscreen canvas.
    // ---------------------------------------------------------------------------

    function drawBarChart(canvas: HTMLCanvasElement, d: Distribution, c: ChartCfg): Chart | undefined {
        const { bins, counts } = d;
        const n = counts.length;
        if (n === 0) return undefined;
        const totalCount = counts.reduce((a, b) => a + b, 0);
        const labels = bins.map(b => c.formatBin ? c.formatBin(b) : String(b));
        const bgColors = bins.map((b, i) => c.barColor(b, i, bins));
        const hoverColors = bgColors.map(col => {
            const r = parseInt(col.slice(1, 3), 16);
            const g = parseInt(col.slice(3, 5), 16);
            const bVal = parseInt(col.slice(5, 7), 16);
            return `rgb(${Math.min(255, r + 40)}, ${Math.min(255, g + 40)}, ${Math.min(255, bVal + 40)})`;
        });
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const annotations: Record<string, any> = {};
        if (c.refLine != null && bins.length >= 2) {
            annotations.refLine = {
                type: 'line', scaleID: 'x', value: _findBinIndex(bins, c.refLine),
                borderColor: '#f44336', borderWidth: 1.5, borderDash: [4, 3],
                label: { display: true, content: c.refLabel || '', position: 'start', color: '#f44336', font: { size: 9, family: 'monospace' }, backgroundColor: 'rgba(15,15,35,0.7)' },
            };
        }
        if (d.percentiles && bins.length >= 2) {
            const pCfg: Record<string, { color: string; dash: number[]; label: string }> = {
                p25: { color: '#888', dash: [3, 3], label: 'P25' },
                p50: { color: '#e0e040', dash: [6, 3], label: 'Med' },
                p75: { color: '#888', dash: [3, 3], label: 'P75' },
            };
            for (const [key, val] of Object.entries(d.percentiles)) {
                const pc = pCfg[key];
                if (!pc) continue;
                const fmtVal = c.formatBin ? c.formatBin(val) : String(val);
                annotations[key] = {
                    type: 'line', scaleID: 'x', value: _findBinIndex(bins, val),
                    borderColor: pc.color, borderWidth: 1, borderDash: pc.dash,
                    label: { display: true, content: `${pc.label} ${fmtVal}`, position: 'start', color: pc.color, font: { size: 8, family: 'monospace' }, backgroundColor: 'rgba(15,15,35,0.7)' },
                };
            }
        }
        const config: ChartConfiguration<'bar'> = {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    data: counts,
                    backgroundColor: bgColors,
                    hoverBackgroundColor: hoverColors,
                    borderWidth: 0,
                    borderSkipped: false,
                    barPercentage: 0.92,
                    categoryPercentage: 0.92,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 200 },
                layout: { padding: { top: 4, right: 4, bottom: 0, left: 0 } },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: '#16213e', borderColor: '#4cc9f0', borderWidth: 1,
                        titleColor: '#4cc9f0', bodyColor: '#e0e0e0', footerColor: '#888',
                        titleFont: { family: 'monospace', size: 11 },
                        bodyFont: { family: 'monospace', size: 11 },
                        footerFont: { family: 'monospace', size: 10 },
                        padding: 6, displayColors: false,
                        callbacks: {
                            title: (items: TooltipItem<'bar'>[]) => items[0]?.label || '',
                            label: (item: TooltipItem<'bar'>) => `Count: ${item.raw}`,
                            footer: (items: TooltipItem<'bar'>[]) => {
                                const count = (items[0]?.raw as number) || 0;
                                return `${(count / totalCount * 100).toFixed(1)}%`;
                            },
                        },
                    },
                    // Annotation plugin lives outside core Chart.js types; attach via cast.
                    ...(({ annotation: { annotations } } as unknown as object)),
                },
                scales: {
                    x: {
                        grid: { color: '#2a2a4a', lineWidth: 0.5 },
                        ticks: { color: '#888', font: { family: 'monospace', size: 9 }, autoSkip: !c.showAllLabels, maxRotation: 45, minRotation: 0 },
                        border: { color: '#2a2a4a' },
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: '#1a1a3e', lineWidth: 0.5 },
                        ticks: { color: '#888', font: { family: 'monospace', size: 10 } },
                        border: { color: '#2a2a4a' },
                    },
                },
            },
        };
        return new Chart(canvas, config);
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
