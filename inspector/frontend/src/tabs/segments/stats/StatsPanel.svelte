<script lang="ts">
    /**
     * StatsPanel — Segmentation Statistics accordion panel.
     *
     * Subscribes to $segStats. When null, renders nothing (hidden).
     * When data is present, renders a <details> panel with 5 histogram
     * chart cards via StatsChart.svelte.
     *
     * Fullscreen: clicking a chart's fullscreen button sets
     * `fullscreenDist` + `fullscreenCfg`; ChartFullscreen.svelte renders
     * the overlay.
     */
    import { segStats } from '../../../lib/stores/segments/stats';
    import { selectedReciter } from '../../../lib/stores/segments/chapter';
    import type { Distribution, ChartCfg } from '../../../lib/types/stats';
    import StatsChart from './StatsChart.svelte';
    import ChartFullscreen from './ChartFullscreen.svelte';

    // Fullscreen overlay state — null = hidden.
    let fullscreenDist: Distribution | null = null;
    let fullscreenCfg: ChartCfg | null = null;

    function openFullscreen(dist: Distribution, cfg: ChartCfg): void {
        fullscreenDist = dist;
        fullscreenCfg = cfg;
    }

    function closeFullscreen(): void {
        fullscreenDist = null;
        fullscreenCfg = null;
    }

    // ---------------------------------------------------------------------------
    // Build the list of chart configurations from the loaded stats data.
    // ---------------------------------------------------------------------------

    $: data = $segStats;
    $: reciter = $selectedReciter;

    $: charts = data
        ? buildCharts(data.vad_params ?? { min_silence_ms: 300 })
        : [];

    function buildCharts(vad: { min_silence_ms: number }): ChartCfg[] {
        return [
            {
                key: 'pause_duration_ms',
                title: 'Pause Duration (ms)',
                refLine: vad.min_silence_ms,
                refLabel: 'threshold',
                barColor: (bin) => bin < vad.min_silence_ms ? '#666' : '#4cc9f0',
                formatBin: v => v >= 3000 ? '3000+' : String(v),
            },
            {
                key: 'seg_duration_ms',
                title: 'Segment Duration (ms)',
                barColor: (bin) => bin < 1000 ? '#ff9800' : '#4cc9f0',
                formatBin: v => (v / 1000).toFixed(1) + 's',
                showAllLabels: true,
            },
            {
                key: 'words_per_seg',
                title: 'Words Per Segment',
                barColor: (bin) => bin === 1 ? '#f44336' : '#4cc9f0',
                formatBin: v => String(v),
                showAllLabels: true,
            },
            {
                key: 'segs_per_verse',
                title: 'Segments Per Verse',
                barColor: () => '#4cc9f0',
                formatBin: v => v >= 8 ? '8+' : String(v),
            },
            {
                key: 'confidence',
                title: 'Confidence (%)',
                barColor: (bin) => bin < 60 ? '#f44336' : bin < 80 ? '#ff9800' : '#4caf50',
                formatBin: v => v >= 100 ? '100' : String(v),
            },
        ];
    }
</script>

{#if data}
    <details class="seg-stats-panel">
        <summary class="seg-stats-summary">Segmentation Statistics</summary>
        <div class="seg-stats-charts">
            {#each charts as cfg (cfg.key)}
                {@const dist = data.distributions?.[cfg.key]}
                {#if dist != null}
                    <StatsChart
                        title={cfg.title}
                        {dist}
                        {cfg}
                        {reciter}
                        onOpenFullscreen={openFullscreen}
                    />
                {/if}
            {/each}
        </div>
    </details>
{/if}

<ChartFullscreen
    dist={fullscreenDist}
    cfg={fullscreenCfg}
    {reciter}
    onClose={closeFullscreen}
/>
