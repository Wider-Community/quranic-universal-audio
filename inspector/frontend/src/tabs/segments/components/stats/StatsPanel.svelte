<script lang="ts">
    /**
     * StatsPanel — Segmentation Statistics accordion panel.
     *
     * Lazy-fetched: stats are computed server-side from a full pass over
     * detailed.json (~0.7-1.2 s cold on production-sized reciters), so we
     * defer the fetch until the user opens the accordion. The panel rarely
     * gets opened during editing, and the values barely shift per edit;
     * paying the cost on demand keeps autosave roundtrips cheap.
     *
     * Fullscreen: clicking a chart's fullscreen button sets
     * `fullscreenDist` + `fullscreenCfg`; ChartFullscreen.svelte renders
     * the overlay.
     */
    import { selectedReciter } from '../../stores/chapter';
    import { segStats } from '../../stores/stats';
    import type { ChartCfg,Distribution } from '../../types/stats';
    import { CONF_HIGH_THRESHOLD, CONF_MID_THRESHOLD, SHORT_SEG_WARN_MS, VAD_MIN_SILENCE_FALLBACK_MS } from '../../utils/constants';
    import { refreshStats } from '../../utils/validation/refresh';
    import ChartFullscreen from './ChartFullscreen.svelte';
    import StatsChart from './StatsChart.svelte';

    // Fullscreen overlay state — null = hidden.
    let fullscreenDist: Distribution | null = null;
    let fullscreenCfg: ChartCfg | null = null;

    // Lazy-fetch state. Fetch on every open so post-save stats are fresh;
    // server-side cache short-circuits when no save invalidated it.
    let isLoading = false;
    function onToggle(e: Event): void {
        const detailsEl = e.currentTarget as HTMLDetailsElement;
        if (!detailsEl.open) return;
        isLoading = true;
        void refreshStats().finally(() => { isLoading = false; });
    }

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
        ? buildCharts(data.vad_params ?? { min_silence_ms: VAD_MIN_SILENCE_FALLBACK_MS })
        : [];

    function buildCharts(vad: {
        min_silence_ms: number;
        min_silence_floor_ms?: number;
    }): ChartCfg[] {
        const refLines = [
            { value: vad.min_silence_ms, label: 'threshold' },
        ];
        if (vad.min_silence_floor_ms && vad.min_silence_floor_ms > 0) {
            refLines.push({
                value: vad.min_silence_floor_ms,
                label: 'floor',
                color: '#9c27b0',
                dash: [2, 4],
            } as never);
        }
        return [
            {
                key: 'pause_duration_ms',
                title: 'Pause Duration (ms)',
                refLines,
                barColor: (bin) => bin < vad.min_silence_ms ? '#666' : '#4cc9f0',
                formatBin: v => v >= 3000 ? '3000+' : String(v),
            },
            {
                key: 'seg_duration_ms',
                title: 'Segment Duration (ms)',
                barColor: (bin) => bin < SHORT_SEG_WARN_MS ? '#ff9800' : '#4cc9f0',
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
                barColor: (bin) => bin < CONF_MID_THRESHOLD * 100 ? '#f44336' : bin < CONF_HIGH_THRESHOLD * 100 ? '#ff9800' : '#4caf50',
                formatBin: v => v >= 100 ? '100' : String(v),
            },
        ];
    }
</script>

<details class="seg-stats-panel" on:toggle={onToggle}>
    <summary class="seg-stats-summary">Segmentation Statistics</summary>
    <div class="seg-stats-charts">
        {#if data}
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
        {:else if isLoading}
            <div class="seg-stats-loading">Loading…</div>
        {:else}
            <div class="seg-stats-loading">No stats loaded.</div>
        {/if}
    </div>
</details>

<ChartFullscreen
    dist={fullscreenDist}
    cfg={fullscreenCfg}
    {reciter}
    onClose={closeFullscreen}
/>
