<script lang="ts">
    /**
     * CoveragePill — mono numeric pill for Quran chapter coverage.
     * `chapterCount === total` renders as the exact number.
     * Partial coverage renders with a leading `~` prefix.
     */
    export let chapterCount: number;
    export let total = 114;

    $: partial = chapterCount < total;
</script>

<span class="pill" class:partial>
    {chapterCount}
</span>

<style>
    .pill {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 1px 6px;
        font-family: var(--font-mono);
        font-size: 10.5px;
        color: var(--text-muted);
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        font-variant-numeric: tabular-nums;
    }
    .pill.partial { color: var(--text-faint); }
    .pill.partial::before { content: '~'; opacity: 0.6; }
</style>
