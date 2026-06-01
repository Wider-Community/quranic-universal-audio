<script lang="ts">
    /** Full-width scrub bar + time readout. Click + drag to seek. Pointer
     *  hover / drag also publishes the hovered time to `progressHoverMs` so the
     *  dashboard now-reciting filmstrip can preview the matching ayah cell. */
    import { createEventDispatcher, onDestroy } from 'svelte';

    import { progressHoverMs, progressScrubMs } from '../../stores/progress-hover';

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
        // Drag owns the scrub signal (scrolls the filmstrip); drop any hover
        // preview so the two don't show at once.
        progressHoverMs.set(null);
        progressScrubMs.set(dragRatio * durationMs);
        (ev.currentTarget as HTMLElement).setPointerCapture(ev.pointerId);
        window.addEventListener('pointermove', onPointerMove);
        window.addEventListener('pointerup', onPointerUp, { once: true });
    }
    function onPointerMove(ev: PointerEvent): void {
        if (!dragging) return;
        dragRatio = ratioFromX(ev.clientX);
        progressScrubMs.set(dragRatio * durationMs);
    }
    function onPointerUp(ev: PointerEvent): void {
        if (!dragging) return;
        const final = ratioFromX(ev.clientX);
        dragging = false;
        window.removeEventListener('pointermove', onPointerMove);
        progressScrubMs.set(null);
        dispatch('seek', final * durationMs);
    }

    // Hover (non-drag) → publish the time under the pointer for the filmstrip.
    function onHover(ev: PointerEvent): void {
        if (dragging || durationMs <= 0) return;
        progressHoverMs.set(ratioFromX(ev.clientX) * durationMs);
    }
    function onLeave(): void {
        if (!dragging) progressHoverMs.set(null);
    }

    onDestroy(() => {
        window.removeEventListener('pointermove', onPointerMove);
        progressHoverMs.set(null);
        progressScrubMs.set(null);
    });
</script>

<div class="progress">
    <span class="time pos">{fmt(shownPos)}</span>
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
        on:pointermove={onHover}
        on:pointerleave={onLeave}
    >
        <div class="track">
            <div class="fill" style={`width: ${pct}%`}></div>
            <div class="thumb" style={`left: ${pct}%`}></div>
        </div>
    </div>
    <span class="time dur">{fmt(durationMs)}</span>
</div>

<style>
    .progress {
        display: flex;
        align-items: center;
        width: 100%;
        gap: var(--s-3);
    }
    .time {
        font-family: var(--font-mono);
        font-size: 10.5px;
        color: var(--text-muted);
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
        flex-shrink: 0;
    }
    .bar {
        position: relative;
        flex: 1;
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
</style>
