/**
 * Stats panel with Chart.js bar charts (histograms with percentile annotations).
 */

import type { ChartConfiguration, TooltipItem } from 'chart.js';

import { fetchJson } from '../lib/api';
import { Chart } from '../lib/utils/chart';
import type { SegSaveChartResponse, SegStatsResponse } from '../types/api';
import { dom,state } from './state';

void state; // unused import placeholder — kept for parity with legacy file

interface Distribution {
    bins: number[];
    counts: number[];
    percentiles?: Record<string, number>;
}

interface ChartCfg {
    key: string;
    title: string;
    refLine?: number;
    refLabel?: string;
    barColor: (bin: number, i?: number, bins?: number[]) => string;
    formatBin?: (v: number) => string;
    showAllLabels?: boolean;
}

/** Canvas augmented with a live Chart.js instance reference. */
interface ChartCanvas extends HTMLCanvasElement {
    _chartInstance?: Chart | null;
}

// ---------------------------------------------------------------------------
// renderStatsPanel -- build all distribution charts
// ---------------------------------------------------------------------------

export function renderStatsPanel(data: SegStatsResponse | null | undefined): void {
    if (!data || (data as { error?: string }).error) return;
    dom.segStatsPanel.hidden = false;
    const vad = data.vad_params ?? { min_silence_ms: 300 };
    const charts: ChartCfg[] = [
        { key: 'pause_duration_ms', title: 'Pause Duration (ms)', refLine: vad.min_silence_ms, refLabel: 'threshold', barColor: (bin) => bin < vad.min_silence_ms ? '#666' : '#4cc9f0', formatBin: v => v >= 3000 ? '3000+' : String(v) },
        { key: 'seg_duration_ms', title: 'Segment Duration (ms)', barColor: (bin) => bin < 1000 ? '#ff9800' : '#4cc9f0', formatBin: v => (v/1000).toFixed(1) + 's', showAllLabels: true },
        { key: 'words_per_seg', title: 'Words Per Segment', barColor: (bin) => bin === 1 ? '#f44336' : '#4cc9f0', formatBin: v => String(v), showAllLabels: true },
        { key: 'segs_per_verse', title: 'Segments Per Verse', barColor: () => '#4cc9f0', formatBin: v => v >= 8 ? '8+' : String(v) },
        { key: 'confidence', title: 'Confidence (%)', barColor: (bin) => bin < 60 ? '#f44336' : bin < 80 ? '#ff9800' : '#4caf50', formatBin: v => v >= 100 ? '100' : String(v) },
    ];
    dom.segStatsCharts.innerHTML = '';
    for (const cfg of charts) {
        const dist = data.distributions?.[cfg.key];
        if (!dist) continue;
        const wrap = document.createElement('div'); wrap.className = 'seg-stats-chart-wrap';
        const header = document.createElement('div'); header.className = 'seg-stats-chart-header';
        const h4 = document.createElement('h4'); h4.textContent = cfg.title; header.appendChild(h4);
        const btnGroup = document.createElement('span'); btnGroup.className = 'seg-stats-chart-btns';
        const fsBtn = document.createElement('button'); fsBtn.className = 'seg-stats-chart-btn'; fsBtn.title = 'Full screen'; fsBtn.textContent = '\u26F6';
        const saveBtn = document.createElement('button'); saveBtn.className = 'seg-stats-chart-btn'; saveBtn.title = 'Save PNG'; saveBtn.textContent = '\u2B73';
        btnGroup.appendChild(fsBtn); btnGroup.appendChild(saveBtn); header.appendChild(btnGroup); wrap.appendChild(header);
        const canvasWrap = document.createElement('div'); canvasWrap.style.position = 'relative'; canvasWrap.style.width = '100%'; canvasWrap.style.height = '160px';
        const canvas = document.createElement('canvas') as ChartCanvas; canvasWrap.appendChild(canvas); wrap.appendChild(canvasWrap);
        dom.segStatsCharts.appendChild(wrap);
        drawBarChart(canvas, dist, cfg);
        fsBtn.addEventListener('click', () => _openChartFullscreen(dist, cfg));
        saveBtn.addEventListener('click', () => _saveChart(canvas, cfg.key));
    }
}

// ---------------------------------------------------------------------------
// _openChartFullscreen -- show a chart in a modal overlay
// ---------------------------------------------------------------------------

function _openChartFullscreen(dist: Distribution, cfg: ChartCfg): void {
    let overlay = document.getElementById('seg-stats-fullscreen');
    if (!overlay) {
        overlay = document.createElement('div'); overlay.id = 'seg-stats-fullscreen';
        overlay.innerHTML = '<div class="seg-stats-fs-inner"><div class="seg-stats-fs-bar"><span class="seg-stats-fs-title"></span><button class="seg-stats-chart-btn seg-stats-fs-save" title="Save PNG">\u2B73</button><button class="seg-stats-chart-btn seg-stats-fs-close" title="Close">\u2715</button></div><div style="flex:1;min-height:0;position:relative"><canvas></canvas></div></div>';
        document.body.appendChild(overlay);
        const overlayNonNull = overlay;
        overlay.querySelector<HTMLButtonElement>('.seg-stats-fs-close')?.addEventListener('click', () => { overlayNonNull.style.display = 'none'; });
        overlay.addEventListener('click', (e) => { if (e.target === overlayNonNull) overlayNonNull.style.display = 'none'; });
    }
    overlay.style.display = 'flex';
    const titleEl = overlay.querySelector<HTMLElement>('.seg-stats-fs-title');
    if (titleEl) titleEl.textContent = cfg.title;
    const canvas = overlay.querySelector<ChartCanvas>('canvas');
    if (!canvas) return;
    if (canvas._chartInstance) { canvas._chartInstance.destroy(); canvas._chartInstance = null; }
    requestAnimationFrame(() => { drawBarChart(canvas, dist, cfg); });
    const saveBtn = overlay.querySelector<HTMLButtonElement>('.seg-stats-fs-save');
    if (!saveBtn) return;
    const newBtn = saveBtn.cloneNode(true) as HTMLButtonElement;
    saveBtn.parentNode?.replaceChild(newBtn, saveBtn);
    newBtn.addEventListener('click', () => _saveChart(canvas, cfg.key));
}

// ---------------------------------------------------------------------------
// _saveChart -- POST chart PNG to server
// ---------------------------------------------------------------------------

function _saveChart(canvas: ChartCanvas, key: string): void {
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;
    canvas.toBlob((blob) => {
        if (!blob) return;
        const fd = new FormData(); fd.append('name', key); fd.append('image', blob, key + '.png');
        fetchJson<SegSaveChartResponse>(
            `/api/seg/stats/${encodeURIComponent(reciter)}/save-chart`,
            { method: 'POST', body: fd },
        ).then((data) => { if (data.ok) { const tip = document.createElement('span'); tip.className = 'seg-stats-saved-tip'; tip.textContent = 'Saved'; document.body.appendChild(tip); setTimeout(() => tip.remove(), 1200); } });
    }, 'image/png');
}

// ---------------------------------------------------------------------------
// _findBinIndex -- locate a value within distribution bins
// ---------------------------------------------------------------------------

function _findBinIndex(bins: number[], value: number): number {
    if (bins.length < 2) return 0;
    const binStep = (bins[1] ?? 0) - (bins[0] ?? 0);
    if (binStep === 0) return 0;
    return Math.max(-0.5, Math.min(bins.length - 0.5, (value - (bins[0] ?? 0)) / binStep));
}

// ---------------------------------------------------------------------------
// drawBarChart -- render a Chart.js bar chart with annotations
// ---------------------------------------------------------------------------

export function drawBarChart(canvas: ChartCanvas, dist: Distribution, cfg: ChartCfg): Chart | undefined {
    const { bins, counts } = dist;
    const n = counts.length;
    if (n === 0) return undefined;
    if (canvas._chartInstance) { canvas._chartInstance.destroy(); canvas._chartInstance = null; }
    const totalCount = counts.reduce((a, b) => a + b, 0);
    const labels = bins.map(b => cfg.formatBin ? cfg.formatBin(b) : String(b));
    const bgColors = bins.map((b, i) => cfg.barColor(b, i, bins));
    const hoverColors = bgColors.map(c => { const r = parseInt(c.slice(1, 3), 16), g = parseInt(c.slice(3, 5), 16), b = parseInt(c.slice(5, 7), 16); return `rgb(${Math.min(255, r + 40)}, ${Math.min(255, g + 40)}, ${Math.min(255, b + 40)})`; });
    // Chart.js annotation plugin types live in a separate package and are
    // verbose to spell out; cast to a loose record here. Budget: 1 `any`.
    const annotations: Record<string, any> = {};
    if (cfg.refLine != null && bins.length >= 2) {
        annotations.refLine = { type: 'line', scaleID: 'x', value: _findBinIndex(bins, cfg.refLine), borderColor: '#f44336', borderWidth: 1.5, borderDash: [4, 3], label: { display: true, content: cfg.refLabel || '', position: 'start', color: '#f44336', font: { size: 9, family: 'monospace' }, backgroundColor: 'rgba(15,15,35,0.7)' } };
    }
    if (dist.percentiles && bins.length >= 2) {
        const pCfg: Record<string, { color: string; dash: number[]; label: string }> = {
            p25: { color: '#888', dash: [3, 3], label: 'P25' },
            p50: { color: '#e0e040', dash: [6, 3], label: 'Med' },
            p75: { color: '#888', dash: [3, 3], label: 'P75' },
        };
        for (const [key, val] of Object.entries(dist.percentiles)) {
            const pc = pCfg[key];
            if (!pc) continue;
            const fmtVal = cfg.formatBin ? cfg.formatBin(val) : String(val);
            annotations[key] = { type: 'line', scaleID: 'x', value: _findBinIndex(bins, val), borderColor: pc.color, borderWidth: 1, borderDash: pc.dash, label: { display: true, content: `${pc.label} ${fmtVal}`, position: 'start', color: pc.color, font: { size: 8, family: 'monospace' }, backgroundColor: 'rgba(15,15,35,0.7)' } };
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
                ...(({ annotation: { annotations } as any })),
            },
            scales: {
                x: {
                    grid: { color: '#2a2a4a', lineWidth: 0.5 },
                    ticks: { color: '#888', font: { family: 'monospace', size: 9 }, autoSkip: !cfg.showAllLabels, maxRotation: 45, minRotation: 0 },
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
    const chart = new Chart(canvas, config);
    canvas._chartInstance = chart;
    return chart;
}
