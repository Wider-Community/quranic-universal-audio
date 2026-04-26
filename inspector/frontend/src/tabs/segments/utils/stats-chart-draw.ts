/**
 * stats-chart-draw.ts — shared Chart.js bar-chart renderer for stats.
 *
 * Shared by StatsChart.svelte and ChartFullscreen.svelte.
 * No Svelte dependency — takes a canvas, distribution data, and chart config
 * and returns a Chart instance.
 */

import type { ChartConfiguration, TooltipItem } from 'chart.js';

import { Chart } from '../../../lib/utils/chart';
import type { ChartCfg, Distribution } from '../types/stats';

// ---------------------------------------------------------------------------
// findBinIndex — locate a value within distribution bins.
// ---------------------------------------------------------------------------

export function findBinIndex(bins: number[], value: number): number {
    if (bins.length < 2) return 0;
    const binStep = (bins[1] ?? 0) - (bins[0] ?? 0);
    if (binStep === 0) return 0;
    return Math.max(-0.5, Math.min(bins.length - 0.5, (value - (bins[0] ?? 0)) / binStep));
}

// ---------------------------------------------------------------------------
// drawBarChart — render a Chart.js bar chart with annotations.
// (Adapted from segments/stats.ts — same axes, colors, and annotations.)
// ---------------------------------------------------------------------------

export function drawBarChart(canvas: HTMLCanvasElement, d: Distribution, c: ChartCfg): Chart | undefined {
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
     
    const annotations: Record<string, any> = {};
    if (c.refLine != null && bins.length >= 2) {
        annotations.refLine = {
            type: 'line', scaleID: 'x', value: findBinIndex(bins, c.refLine),
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
                type: 'line', scaleID: 'x', value: findBinIndex(bins, val),
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
