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
    import { onMount } from 'svelte';

    import { THEME_CHANGE_EVENT } from '../../../../lib/stores/theme.svelte';
    import { themeColor } from '../../../../lib/utils/canvas-theme';
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

    // Bumped on each theme flip so `charts` recomputes — rebuilds the chart
    // cfgs (incl. the eagerly-resolved floor refline colour) with fresh tokens.
    let themeTick = 0;
    onMount(() => {
        const onThemeChange = (): void => { themeTick += 1; };
        window.addEventListener(THEME_CHANGE_EVENT, onThemeChange);
        return () => window.removeEventListener(THEME_CHANGE_EVENT, onThemeChange);
    });

    $: charts = buildChartsForTheme(data, themeTick);

    function buildChartsForTheme(
        d: typeof data,
        _themeTick: number,
    ): ChartCfg[] {
        // `_themeTick` is an explicit dep so a theme flip rebuilds the cfgs
        // (incl. the eagerly-resolved floor refline colour) with fresh tokens.
        return d
            ? buildCharts(d.vad_params ?? { min_silence_ms: VAD_MIN_SILENCE_FALLBACK_MS })
            : [];
    }

    function buildCharts(vad: {
        min_silence_ms: number;
        min_silence_floor_ms?: number;
    }): ChartCfg[] {
        // Bar/refline colours resolve their --chart-* tokens lazily — these
        // callbacks run at chart-build time (drawBarChart), and StatsChart/
        // ChartFullscreen rebuild on `themechange`, so each build picks up the
        // active theme. The hex fallbacks match the dark token values.
        const bar      = (): string => themeColor('--chart-bar', '#4cc9f0');
        const barMuted = (): string => themeColor('--chart-bar-muted', '#666666');
        const barWarn  = (): string => themeColor('--chart-bar-warn', '#ff9800');
        const barBad   = (): string => themeColor('--chart-bar-bad', '#f44336');
        const barGood  = (): string => themeColor('--chart-bar-good', '#4caf50');

        const refLines = [
            { value: vad.min_silence_ms, label: 'threshold' },
        ];
        if (vad.min_silence_floor_ms && vad.min_silence_floor_ms > 0) {
            refLines.push({
                value: vad.min_silence_floor_ms,
                label: 'floor',
                color: themeColor('--chart-refline-floor', '#9c27b0'),
                dash: [2, 4],
            } as never);
        }
        return [
            {
                key: 'pause_duration_ms',
                title: 'Pause Duration (ms)',
                refLines,
                barColor: (bin) => bin < vad.min_silence_ms ? barMuted() : bar(),
                formatBin: v => v >= 3000 ? '3000+' : String(v),
            },
            {
                key: 'seg_duration_ms',
                title: 'Segment Duration (ms)',
                barColor: (bin) => bin < SHORT_SEG_WARN_MS ? barWarn() : bar(),
                formatBin: v => (v / 1000).toFixed(1) + 's',
                showAllLabels: true,
            },
            {
                key: 'words_per_seg',
                title: 'Words Per Segment',
                barColor: (bin) => bin === 1 ? barBad() : bar(),
                formatBin: v => String(v),
                showAllLabels: true,
            },
            {
                key: 'segs_per_verse',
                title: 'Segments Per Verse',
                barColor: () => bar(),
                formatBin: v => v >= 8 ? '8+' : String(v),
            },
            {
                key: 'confidence',
                title: 'Confidence (%)',
                barColor: (bin) => bin < CONF_MID_THRESHOLD * 100 ? barBad() : bin < CONF_HIGH_THRESHOLD * 100 ? barWarn() : barGood(),
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
