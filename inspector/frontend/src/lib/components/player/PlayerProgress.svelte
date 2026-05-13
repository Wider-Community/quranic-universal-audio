<script lang="ts">
    /** Full-width scrub bar + time readout. Click + drag to seek. */
    import { createEventDispatcher, onDestroy } from 'svelte';

    export let positionMs = 0;
    export let durationMs = 0;

    const dispatch = createEventDispatcher<{ seek: number }>();

    let barEl: HTMLDivElement | null = null;
    let dragging = false;
    let dragRatio = 0;

    $: pct = dragging
        ? dragRatio * 100
        : durationMs > 0
          ? Math.min(100, (positionMs / durationMs) * 100)
          : 0;
    $: shownPos = dragging ? dragRatio * durationMs : positionMs;

    function fmt(ms: number): string {
        if (!ms || !isFinite(ms)) return '0:00:00';
        const total = Math.floor(ms / 1000);
        const h = Math.floor(total / 3600);
        const m = Math.floor((total % 3600) / 60);
        const s = total % 60;
        return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }

    function ratioFromX(clientX: number): number {
        if (!barEl) return 0;
        const rect = barEl.getBoundingClientRect();
        return Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    }

    function onPointerDown(ev: PointerEvent): void {
        if (durationMs <= 0) return;
        dragging = true;
        dragRatio = ratioFromX(ev.clientX);
        (ev.currentTarget as HTMLElement).setPointerCapture(ev.pointerId);
        window.addEventListener('pointermove', onPointerMove);
        window.addEventListener('pointerup', onPointerUp, { once: true });
    }
    function onPointerMove(ev: PointerEvent): void {
        if (!dragging) return;
        dragRatio = ratioFromX(ev.clientX);
    }
    function onPointerUp(ev: PointerEvent): void {
        if (!dragging) return;
        const final = ratioFromX(ev.clientX);
        dragging = false;
        window.removeEventListener('pointermove', onPointerMove);
        dispatch('seek', final * durationMs);
    }

    onDestroy(() => {
        window.removeEventListener('pointermove', onPointerMove);
    });
</script>

<div class="progress">
    <div
        class="bar"
        bind:this={barEl}
        role="slider"
        aria-label="Playback position"
        aria-valuemin={0}
        aria-valuemax={durationMs}
        aria-valuenow={positionMs}
        tabindex="0"
        on:pointerdown={onPointerDown}
    >
        <div class="track">
            <div class="fill" style={`width: ${pct}%`} />
            <div class="thumb" style={`left: ${pct}%`} />
        </div>
    </div>
    <div class="times">
        <span>{fmt(shownPos)}</span>
        <span>{fmt(durationMs)}</span>
    </div>
</div>

<style>
    .progress {
        display: flex;
        flex-direction: column;
        width: 100%;
    }
    .bar {
        position: relative;
        height: 14px;
        cursor: pointer;
        display: flex;
        align-items: center;
        touch-action: none;
    }
    .track {
        position: relative;
        width: 100%;
        height: 3px;
        background: var(--canvas-inset);
        border-radius: 0;
        overflow: visible;
        transition: height var(--t-fast) ease;
    }
    .bar:hover .track {
        height: 5px;
    }
    .fill {
        height: 100%;
        background: var(--accent);
    }
    .thumb {
        position: absolute;
        top: 50%;
        width: 11px;
        height: 11px;
        margin-left: -5.5px;
        background: var(--accent);
        border-radius: 999px;
        transform: translateY(-50%) scale(0);
        transition: transform var(--t-fast) ease;
        pointer-events: none;
    }
    .bar:hover .thumb,
    .bar:focus-visible .thumb {
        transform: translateY(-50%) scale(1);
    }
    .times {
        display: flex;
        justify-content: space-between;
        padding: 2px var(--s-3) 0;
        font-family: var(--font-mono);
        font-size: 10.5px;
        color: var(--text-muted);
        font-variant-numeric: tabular-nums;
    }
</style>
