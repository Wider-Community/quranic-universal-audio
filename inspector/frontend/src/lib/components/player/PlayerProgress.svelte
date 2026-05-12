<script lang="ts">
    /** Scrub bar + time readout for the BottomPlayer. */
    import { createEventDispatcher } from 'svelte';

    export let positionMs = 0;
    export let durationMs = 0;

    const dispatch = createEventDispatcher<{ seek: number }>();

    $: pct = durationMs > 0 ? Math.min(100, (positionMs / durationMs) * 100) : 0;

    function fmt(ms: number): string {
        if (!ms || !isFinite(ms)) return '0:00';
        const total = Math.floor(ms / 1000);
        const m = Math.floor(total / 60);
        const s = total % 60;
        return `${m}:${s.toString().padStart(2, '0')}`;
    }

    function onBarClick(ev: MouseEvent): void {
        if (durationMs <= 0) return;
        const el = ev.currentTarget as HTMLElement;
        const rect = el.getBoundingClientRect();
        const x = ev.clientX - rect.left;
        const ratio = Math.min(1, Math.max(0, x / rect.width));
        dispatch('seek', ratio * durationMs);
    }
</script>

<div class="progress">
    <!-- svelte-ignore a11y-click-events-have-key-events -->
    <div
        class="bar"
        role="slider"
        aria-label="Playback position"
        aria-valuemin={0}
        aria-valuemax={durationMs}
        aria-valuenow={positionMs}
        tabindex="0"
        on:click={onBarClick}
    >
        <div class="fill" style={`width: ${pct}%`} />
    </div>
    <div class="times">
        <span>{fmt(positionMs)}</span>
        <span>{fmt(durationMs)}</span>
    </div>
</div>

<style>
    .progress {
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
        width: 100%;
    }
    .bar {
        height: 3px;
        background: var(--canvas-inset);
        border-radius: 999px;
        overflow: hidden;
        cursor: pointer;
    }
    .fill {
        height: 100%;
        background: var(--accent);
    }
    .times {
        display: flex;
        justify-content: space-between;
        font-family: var(--font-mono);
        font-size: 10.5px;
        color: var(--text-muted);
        font-variant-numeric: tabular-nums;
    }
</style>
