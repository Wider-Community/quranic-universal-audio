<script lang="ts">
    /**
     * Center-anchored ayah filmstrip — a non-linear, by-ayah scrubber that sits
     * above the (linear) progress bar. Cells = ayahs, width
     * proportional-with-normalization (min/max clamp). A fixed center needle
     * marks "now"; the strip slides so the live playhead stays centered. Manual
     * drag scrubs; click jumps. Three motion models (config.filmstripMotion):
     *   - tuner:  continuous center; drag scrubs exact time.
     *   - hybrid: continuous center; drag snaps to whole ayahs on release.
     *   - snap:   center the active cell only when the ayah changes; drag = snap.
     *
     * Surface-agnostic: fed ayah boundaries + a time accessor + an onSeek cb.
     */
    import { type RecitationAnimConfig } from './config';
    import type { AyahBoundary } from './types';

    interface Props {
        ayahs: AyahBoundary[];
        durationMs: number;
        getTimeMs: () => number;
        playing: boolean;
        config: RecitationAnimConfig;
        onSeek: (ms: number) => void;
    }

    let { ayahs, getTimeMs, playing, config, onSeek }: Props = $props();

    const clamp = (lo: number, hi: number, v: number): number => Math.min(hi, Math.max(lo, v));
    const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

    let containerEl = $state<HTMLDivElement | undefined>(undefined);
    let cw = $state(0); // container width
    let nowMs = $state(0);
    let offset = $state(0); // px scrolled into the cells region (needle position)
    let animate = $state(false); // CSS transition on the track (snap moves only)
    let dragging = $state(false);

    interface Cell {
        ayah: number;
        startMs: number;
        endMs: number;
        dur: number;
        w: number;
        cumBefore: number; // px before this cell's left (cells + gaps)
    }

    const cells = $derived.by((): Cell[] => {
        if (!ayahs.length) return [];
        const durs = ayahs.map((a) => Math.max(1, a.endMs - a.startMs));
        const maxDur = Math.max(...durs);
        const out: Cell[] = [];
        let cum = 0;
        for (let i = 0; i < ayahs.length; i++) {
            const propW = (durs[i]! / maxDur) * config.filmstripMaxCellPx;
            const w = Math.round(
                clamp(
                    config.filmstripMinCellPx,
                    config.filmstripMaxCellPx,
                    lerp(config.filmstripMinCellPx, propW, config.filmstripProportional),
                ),
            );
            out.push({
                ayah: ayahs[i]!.ayah,
                startMs: ayahs[i]!.startMs,
                endMs: ayahs[i]!.endMs,
                dur: durs[i]!,
                w,
                cumBefore: cum,
            });
            cum += w + config.filmstripGapPx;
        }
        return out;
    });

    const lastRight = $derived(
        cells.length ? cells[cells.length - 1]!.cumBefore + cells[cells.length - 1]!.w : 0,
    );
    const pad = $derived(cw / 2); // leading/trailing spacer so edges can center

    function indexForTime(t: number): number {
        let last = -1;
        for (let i = 0; i < cells.length; i++) {
            const c = cells[i]!;
            if (t >= c.startMs && t < c.endMs) return i;
            if (t >= c.startMs) last = i;
        }
        return last;
    }
    const activeIdx = $derived(indexForTime(nowMs));

    function fill(i: number): number {
        const c = cells[i];
        if (!c) return 0;
        return clamp(0, 1, (nowMs - c.startMs) / c.dur);
    }

    function offsetForCellCenter(i: number): number {
        const c = cells[i];
        return c ? c.cumBefore + c.w / 2 : 0;
    }
    function continuousOffset(t: number): number {
        const i = indexForTime(t);
        if (i < 0) return 0;
        const c = cells[i]!;
        return c.cumBefore + clamp(0, 1, (t - c.startMs) / c.dur) * c.w;
    }
    function timeAtOffset(off: number): number {
        for (let i = 0; i < cells.length; i++) {
            const c = cells[i]!;
            if (off <= c.cumBefore + c.w) {
                const f = clamp(0, 1, (off - c.cumBefore) / c.w);
                return c.startMs + f * c.dur;
            }
        }
        return cells.length ? cells[cells.length - 1]!.endMs : 0;
    }
    function nearestCell(off: number): number {
        let best = -1;
        let bestD = Infinity;
        for (let i = 0; i < cells.length; i++) {
            const d = Math.abs(offsetForCellCenter(i) - off);
            if (d < bestD) {
                bestD = d;
                best = i;
            }
        }
        return best;
    }

    // rAF while playing: track time, and (tuner/hybrid) keep the playhead centered.
    $effect(() => {
        if (!playing) return;
        let raf = 0;
        const loop = (): void => {
            nowMs = getTimeMs();
            if (!dragging && config.filmstripMotion !== 'snap') {
                animate = false;
                offset = continuousOffset(nowMs);
            }
            raf = requestAnimationFrame(loop);
        };
        raf = requestAnimationFrame(loop);
        return () => cancelAnimationFrame(raf);
    });

    // Snap mode: glide the active cell to center when the ayah changes.
    $effect(() => {
        void activeIdx;
        if (config.filmstripMotion !== 'snap' || dragging || activeIdx < 0 || cw === 0) return;
        animate = true;
        offset = offsetForCellCenter(activeIdx);
    });

    // Drag — pan the strip; release scrubs (tuner) or snaps to an ayah.
    let dragStartX = 0;
    let dragStartOffset = 0;
    let moved = false;

    function onPointerDown(e: PointerEvent): void {
        dragging = true;
        moved = false;
        dragStartX = e.clientX;
        dragStartOffset = offset;
        animate = false;
        containerEl?.setPointerCapture(e.pointerId);
        window.addEventListener('pointermove', onPointerMove);
        window.addEventListener('pointerup', onPointerUp, { once: true });
    }
    function onPointerMove(e: PointerEvent): void {
        if (!dragging) return;
        const dx = e.clientX - dragStartX;
        if (Math.abs(dx) > 4) moved = true;
        offset = clamp(0, lastRight, dragStartOffset - dx);
    }
    function onPointerUp(e: PointerEvent): void {
        if (!dragging) return;
        dragging = false;
        window.removeEventListener('pointermove', onPointerMove);
        if (!moved) {
            clickToSeek(e.clientX);
            return;
        }
        if (config.filmstripMotion === 'tuner') {
            onSeek(timeAtOffset(offset));
        } else {
            const i = nearestCell(offset);
            if (i >= 0) {
                animate = true;
                offset = offsetForCellCenter(i);
                onSeek(cells[i]!.startMs);
            }
        }
    }
    function clickToSeek(clientX: number): void {
        if (!containerEl) return;
        const rect = containerEl.getBoundingClientRect();
        // viewport-x → offset into cells region (needle is at cw/2; track is
        // translated by -offset; leading pad = cw/2).
        const off = clientX - rect.left + offset - cw / 2;
        const i = nearestCell(clamp(0, lastRight, off));
        if (i < 0) return;
        animate = true;
        offset = offsetForCellCenter(i);
        onSeek(cells[i]!.startMs);
    }

    /** Re-sync after a seek while paused (parent calls this). */
    export function refresh(): void {
        nowMs = getTimeMs();
        if (cw === 0) return;
        animate = true;
        offset = config.filmstripMotion === 'tuner'
            ? continuousOffset(nowMs)
            : (activeIdx >= 0 ? offsetForCellCenter(activeIdx) : offset);
    }
</script>

{#if config.filmstripShow && cells.length}
    <div
        class="filmstrip"
        bind:this={containerEl}
        bind:clientWidth={cw}
        style:height="{config.filmstripHeightPx}px"
        role="slider"
        tabindex="0"
        aria-label="Ayah scrubber"
        aria-valuemin={cells[0]!.ayah}
        aria-valuemax={cells[cells.length - 1]!.ayah}
        aria-valuenow={activeIdx >= 0 ? cells[activeIdx]!.ayah : cells[0]!.ayah}
        onpointerdown={onPointerDown}
        onkeydown={(e) => {
            if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
                e.preventDefault();
                const d = e.key === 'ArrowRight' ? 1 : -1;
                const i = clamp(0, cells.length - 1, (activeIdx < 0 ? 0 : activeIdx) + d);
                animate = true;
                offset = offsetForCellCenter(i);
                onSeek(cells[i]!.startMs);
            }
        }}
    >
        <div class="track" class:animate style:transform="translateX({-offset}px)">
            <div class="pad" style:width="{pad}px"></div>
            {#each cells as c, i (c.ayah)}
                <div
                    class="cell"
                    class:active={i === activeIdx}
                    class:reached={i < activeIdx}
                    style:width="{c.w}px"
                    style:margin-right="{config.filmstripGapPx}px"
                >
                    <div class="cell-fill" style:width="{fill(i) * 100}%"></div>
                    <span class="cell-num">{c.ayah}</span>
                </div>
            {/each}
            <div class="pad" style:width="{pad}px"></div>
        </div>
        <div class="needle" aria-hidden="true"></div>
        <div class="fade fade-l" aria-hidden="true"></div>
        <div class="fade fade-r" aria-hidden="true"></div>
    </div>
{/if}

<style>
    .filmstrip {
        position: relative;
        width: 100%;
        overflow: hidden;
        touch-action: none;
        cursor: grab;
        user-select: none;
    }
    .filmstrip:active {
        cursor: grabbing;
    }
    .track {
        position: absolute;
        top: 50%;
        left: 0;
        display: flex;
        align-items: center;
        transform: translateX(0);
        will-change: transform;
        translate: 0 -50%;
    }
    .track.animate {
        transition: transform var(--t-base, 200ms) var(--ease-out-quart, ease);
    }
    .pad {
        flex: 0 0 auto;
        height: 1px;
    }
    .cell {
        position: relative;
        flex: 0 0 auto;
        height: calc(100% - 12px);
        min-height: 22px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        overflow: hidden;
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    .cell.reached {
        border-color: var(--border-default);
    }
    .cell.active {
        border-color: var(--accent);
        background: var(--accent-tint-soft);
    }
    .cell-fill {
        position: absolute;
        inset: 0 auto 0 0;
        background: var(--accent-tint);
        pointer-events: none;
    }
    .cell.reached .cell-fill {
        background: var(--accent-tint-soft);
    }
    .cell-num {
        position: relative;
        font-family: var(--font-mono);
        font-size: 11px;
        font-variant-numeric: tabular-nums;
        color: var(--text-muted);
    }
    .cell.active .cell-num {
        color: var(--accent);
    }
    .cell.reached .cell-num {
        color: var(--text-secondary);
    }
    .needle {
        position: absolute;
        top: 4px;
        bottom: 4px;
        left: 50%;
        width: 2px;
        transform: translateX(-50%);
        background: var(--accent);
        border-radius: 1px;
        pointer-events: none;
        box-shadow: 0 0 8px var(--accent-tint);
    }
    .fade {
        position: absolute;
        top: 0;
        bottom: 0;
        width: 40px;
        pointer-events: none;
    }
    .fade-l {
        left: 0;
        background: linear-gradient(to right, var(--panel), transparent);
    }
    .fade-r {
        right: 0;
        background: linear-gradient(to left, var(--panel), transparent);
    }
    @media (prefers-reduced-motion: reduce) {
        .track.animate {
            transition: none;
        }
    }
</style>
