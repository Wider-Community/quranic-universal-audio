<script lang="ts">
    /**
     * Center-anchored ayah filmstrip — a by-ayah scrubber that sits above the
     * (linear) progress bar. Cells = ayahs, width proportional to each verse's
     * canonical recited length (min/max clamp). A fixed center needle marks
     * "now"; the strip slides so the live recited position stays centered.
     *
     * Recitation-driven, not clock-driven: the active cell + its progress fill
     * follow which WORD is being recited (via the shared `findActiveAt`
     * timeline), so silences freeze it and loopbacks travel it backward — the
     * strip and the teleprompter line stay in lockstep. Three motion models
     * (config.filmstripMotion):
     *   - tuner:  continuous center; drag scrubs exact time.
     *   - hybrid: continuous center; drag snaps to whole ayahs on release.
     *   - snap:   center the active cell only when the ayah changes; drag = snap.
     *
     * User scrub/drag/click stays TIME-based (seeking); playback is the only
     * recitation-driven path. Surface-agnostic: fed `units` + a prebuilt
     * `FilmstripModel` + a time accessor + an onSeek cb.
     */
    import { type RecitationAnimConfig } from './config';
    import type { FilmstripModel } from './filmstrip-model';
    import { buildSortedIntervals, findActiveAt } from './recitation-active';
    import type { AnimUnit } from './types';

    interface Props {
        units: AnimUnit[];
        model: FilmstripModel;
        durationMs: number;
        getTimeMs: () => number;
        playing: boolean;
        config: RecitationAnimConfig;
        onSeek: (_ms: number) => void;
        /** Preview-highlight the ayah recited at this time (e.g. progress-bar
         *  hover). null = no preview. */
        hoverMs?: number | null;
        /** Active progress-bar *drag* time — the strip scroll-follows it (both
         *  motion modes) while non-null, suspending the playback driver. null =
         *  not scrubbing. */
        scrubMs?: number | null;
        /** Speculative-prewarm hook: fired with a cell's seek (ms) when the
         *  pointer enters it, so the surface can warm that position. Optional. */
        onHoverPrewarm?: (_ms: number) => void;
    }

    let {
        units, model, getTimeMs, playing, config, onSeek,
        hoverMs = null, scrubMs = null, onHoverPrewarm,
    }: Props = $props();

    const clamp = (lo: number, hi: number, v: number): number => Math.min(hi, Math.max(lo, v));
    const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

    /** A backward verse jump, or a forward verse skip larger than this many
     *  cells, is a loopback/seek discontinuity → glide rather than teleport. */
    const JUMP_CELL_GAP = 1;
    /** Min backward cell-fill delta (fraction) that counts as a within-verse
     *  word loopback worth gliding. */
    const JUMP_FRAC_EPS = 0.01;
    /** How long the loopback/seek glide eases before direct tracking resumes. */
    const GLIDE_MS = 320;

    let containerEl = $state<HTMLDivElement | undefined>(undefined);
    let cw = $state(0); // container width
    let offset = $state(0); // px scrolled into the cells region (needle position)
    let animate = $state(false); // CSS transition on the track (snap + glide moves)
    let dragging = $state(false);

    // Recitation-driven playback state (written by the rAF driver / refresh).
    let activeIdx = $state(-1); // cell of the recited word; holds during silence
    let cellFrac = $state(0); // word-proportional fill of the active cell
    let silent = $state(false); // in a silence gap → frozen, no highlight/cursor
    let frozenIdx = $state(-1); // last active cell, held while silent
    let jumping = $state(false); // mid-glide → cell-fill eases too
    let lastActiveUnit = -1; // O(1) fast-path hint for findActiveAt
    let glideTimer: ReturnType<typeof setTimeout> | null = null;

    interface Cell {
        ayah: number;
        w: number;
        cumBefore: number; // px before this cell's left (cells + gaps)
    }

    // Cell widths from each verse's CANONICAL recited duration — never inflated
    // by a loopback's later occurrence (unlike the old ayah max-end boundary).
    const cells = $derived.by((): Cell[] => {
        const mc = model.cells;
        if (!mc.length) return [];
        const durs = mc.map((c) => Math.max(1, c.canonDurSec * 1000));
        const maxDur = Math.max(...durs);
        const out: Cell[] = [];
        let cum = 0;
        for (let i = 0; i < mc.length; i++) {
            const propW = (durs[i]! / maxDur) * config.filmstripMaxCellPx;
            const w = Math.round(
                clamp(
                    config.filmstripMinCellPx,
                    config.filmstripMaxCellPx,
                    lerp(config.filmstripMinCellPx, propW, config.filmstripProportional),
                ),
            );
            out.push({ ayah: mc[i]!.ayah, w, cumBefore: cum });
            cum += w + config.filmstripGapPx;
        }
        return out;
    });

    const sorted = $derived(buildSortedIntervals(units));
    const lastRight = $derived(
        cells.length ? cells[cells.length - 1]!.cumBefore + cells[cells.length - 1]!.w : 0,
    );
    const pad = $derived(cw / 2); // leading/trailing spacer so edges can center

    interface Reci { unitIdx: number; idx: number; frac: number; }

    /** Map a time (seconds) to the recited cell + its word-proportional fill,
     *  or null during a silence gap. `hint` seeds the O(1) fast-path (-1 for
     *  random-access lookups like hover/scrub). */
    function recitationAt(tSec: number, hint: number): Reci | null {
        const h = findActiveAt(units, sorted, tSec, hint);
        if (!h) return null;
        const idx = model.cellOfUnit[h.unitIdx] ?? -1;
        if (idx < 0) return null;
        const cell = model.cells[idx]!;
        const wf = cell.words[h.unitIdx - cell.unitStart];
        const span = h.ivEnd - h.ivStart;
        const intra = span > 0 ? clamp(0, 1, (tSec - h.ivStart) / span) : 0;
        const frac = wf ? wf.frac0 + intra * (wf.frac1 - wf.frac0) : 0;
        return { unitIdx: h.unitIdx, idx, frac };
    }

    function offsetForCellCenter(i: number): number {
        const c = cells[i];
        return c ? c.cumBefore + c.w / 2 : 0;
    }
    function offsetForReci(r: Reci): number {
        const c = cells[r.idx];
        return c ? c.cumBefore + r.frac * c.w : offset;
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
    /** Map a strip offset back to a canonical seek time (ms) — tuner drag. */
    function timeAtOffset(off: number): number {
        for (let i = 0; i < cells.length; i++) {
            const c = cells[i]!;
            if (off <= c.cumBefore + c.w) {
                const f = clamp(0, 1, (off - c.cumBefore) / c.w);
                const mc = model.cells[i]!;
                return (mc.canonStartSec + f * mc.canonDurSec) * 1000;
            }
        }
        const last = model.cells[model.cells.length - 1];
        return last ? (last.canonStartSec + last.canonDurSec) * 1000 : 0;
    }
    /** The seek target for picking a cell — the verse's canonical first start. */
    function seekMsForCell(i: number): number {
        const mc = model.cells[i];
        return mc ? mc.canonStartSec * 1000 : 0;
    }
    /** Cell recited at a given time (random access) — hover/scrub preview. */
    function cellViaTime(ms: number): number {
        const h = findActiveAt(units, sorted, ms / 1000, -1);
        return h ? (model.cellOfUnit[h.unitIdx] ?? -1) : -1;
    }

    const hoverIdx = $derived(hoverMs == null ? -1 : cellViaTime(hoverMs));
    // Snap mode has no moving needle (the strip is always centered on the active
    // cell), so instead we ring the cell under where the invisible needle would
    // sit. Hidden during silence (no cursor while frozen). -1 outside snap mode.
    const cursorIdx = $derived(
        config.filmstripMotion === 'snap' && !silent ? nearestCell(offset) : -1,
    );

    function setFill(frac: number): void {
        containerEl?.style.setProperty('--cell-active-fill', clamp(0, 1, frac) * 100 + '%');
    }

    /** A recitation discontinuity (loopback / seek) vs a smooth advance. */
    function isJump(prevIdx: number, newIdx: number, prevFrac: number, newFrac: number): boolean {
        if (prevIdx < 0) return false; // first activation — no glide
        if (newIdx < prevIdx) return true; // back to an earlier verse
        if (newIdx - prevIdx > JUMP_CELL_GAP) return true; // forward verse skip
        if (newIdx === prevIdx && newFrac < prevFrac - JUMP_FRAC_EPS) return true; // word loopback
        return false;
    }
    function triggerGlide(): void {
        jumping = true;
        animate = true;
        if (glideTimer) clearTimeout(glideTimer);
        glideTimer = setTimeout(() => {
            jumping = false;
            // Snap keeps its track transition on (it always glides ayah hops);
            // hybrid/tuner return to direct per-frame writes.
            if (config.filmstripMotion !== 'snap') animate = false;
        }, GLIDE_MS);
    }

    /** One rAF step of recitation-driven playback. */
    function drivePlayback(): void {
        const tSec = (getTimeMs() + config.leadMs) / 1000;
        const r = recitationAt(tSec, lastActiveUnit);
        if (!r) {
            // Silence: freeze — hold offset + fill, drop highlight/cursor. The
            // last active cell (frozenIdx) stays as a de-accented, held bar.
            silent = true;
            return;
        }
        lastActiveUnit = r.unitIdx;
        const jumped = isJump(activeIdx, r.idx, cellFrac, r.frac);
        silent = false;
        activeIdx = r.idx;
        cellFrac = r.frac;
        frozenIdx = r.idx;
        setFill(r.frac);
        if (jumped) triggerGlide();
        if (config.filmstripMotion === 'snap') return; // centering effect owns offset
        if (!jumping) animate = false;
        offset = offsetForReci(r);
    }

    // rAF while playing: drive the recitation mapping (all modes).
    $effect(() => {
        if (!playing) return;
        let raf = 0;
        const loop = (): void => {
            if (!dragging && scrubMs == null) drivePlayback();
            raf = requestAnimationFrame(loop);
        };
        raf = requestAnimationFrame(loop);
        return () => cancelAnimationFrame(raf);
    });

    // Snap mode: glide the active cell to center when the ayah changes (now
    // recitation-driven, so a cross-verse loopback scrolls back here). Yields to
    // a progress-bar scrub (the scroll-follow effect owns offset then).
    $effect(() => {
        void activeIdx;
        if (config.filmstripMotion !== 'snap' || dragging || scrubMs != null
            || silent || activeIdx < 0 || cw === 0) return;
        animate = true;
        offset = offsetForCellCenter(activeIdx);
    });

    // Progress-bar drag → scroll-follow the dragged time (both motion modes).
    // Maps the time through the recitation timeline so it tracks the recited
    // position (correct under overlap/repeats). The playback driver is suspended
    // while scrubMs is non-null. Silence in the scrub → hold (no move).
    $effect(() => {
        if (scrubMs == null || cw === 0) return;
        animate = false;
        const r = recitationAt(scrubMs / 1000, -1);
        if (r) offset = clamp(0, lastRight, offsetForReci(r));
    });

    // Reset recitation state when the chapter (units identity) changes.
    $effect(() => {
        void units; // track
        activeIdx = -1;
        cellFrac = 0;
        silent = false;
        frozenIdx = -1;
        lastActiveUnit = -1;
        if (glideTimer) clearTimeout(glideTimer);
        jumping = false;
        containerEl?.style.removeProperty('--cell-active-fill');
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
                onSeek(seekMsForCell(i));
            }
        }
    }
    function clickToSeek(clientX: number): void {
        if (!containerEl) return;
        const i = cellAtClientX(clientX);
        if (i < 0) return;
        animate = true;
        offset = offsetForCellCenter(i);
        onSeek(seekMsForCell(i));
    }

    /** Map a viewport x to the cell index under it (needle at cw/2; track
     *  translated by -offset; leading pad = cw/2). -1 when out of range. */
    function cellAtClientX(clientX: number): number {
        if (!containerEl) return -1;
        const rect = containerEl.getBoundingClientRect();
        const off = clientX - rect.left + offset - cw / 2;
        return nearestCell(clamp(0, lastRight, off));
    }

    /** Speculative-prewarm hook on pointer hover (no button): warm the seek
     *  position of the cell under the pointer. Suppressed while dragging. */
    function onHoverMove(e: PointerEvent): void {
        if (!onHoverPrewarm || dragging) return;
        const i = cellAtClientX(e.clientX);
        if (i >= 0) onHoverPrewarm(seekMsForCell(i));
    }

    /** Re-sync after a seek while paused (parent calls this). */
    export function refresh(): void {
        if (cw === 0) return;
        const r = recitationAt((getTimeMs() + config.leadMs) / 1000, -1);
        if (!r) {
            // Landed in a gap → hold the frozen state (or nothing, pre-first).
            silent = true;
            return;
        }
        silent = false;
        activeIdx = r.idx;
        cellFrac = r.frac;
        frozenIdx = r.idx;
        lastActiveUnit = r.unitIdx;
        setFill(r.frac);
        animate = true;
        offset = config.filmstripMotion === 'snap'
            ? offsetForCellCenter(r.idx)
            : offsetForReci(r);
    }

    /** Force the new chapter's first ayah into view before audio canplay. */
    export function showFirstAyah(): void {
        if (!cells.length) return;
        activeIdx = -1;
        cellFrac = 0;
        silent = false;
        frozenIdx = -1;
        lastActiveUnit = -1;
        containerEl?.style.removeProperty('--cell-active-fill');
        animate = true;
        offset = offsetForCellCenter(0);
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
        onpointermove={onHoverMove}
        onkeydown={(e) => {
            if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
                e.preventDefault();
                const d = e.key === 'ArrowRight' ? 1 : -1;
                const i = clamp(0, cells.length - 1, (activeIdx < 0 ? 0 : activeIdx) + d);
                animate = true;
                offset = offsetForCellCenter(i);
                onSeek(seekMsForCell(i));
            }
        }}
    >
        <div
            class="track"
            class:animate
            class:snap-glide={config.filmstripMotion === 'snap'}
            style:transform="translateX({-offset}px)"
        >
            <div class="pad" style:width="{pad}px"></div>
            {#each cells as c, i (c.ayah)}
                <div
                    class="cell"
                    class:active={!silent && i === activeIdx}
                    class:reached={i < (silent ? frozenIdx : activeIdx)}
                    class:frozen={silent && i === frozenIdx}
                    class:preview={i === hoverIdx && i !== activeIdx}
                    class:cursor={i === cursorIdx}
                    style:width="{c.w}px"
                    style:margin-right="{config.filmstripGapPx}px"
                >
                    <div class="cell-fill" class:glide={jumping && i === activeIdx}></div>
                    <span class="cell-num">{c.ayah}</span>
                </div>
            {/each}
            <div class="pad" style:width="{pad}px"></div>
        </div>
        {#if config.filmstripMotion !== 'snap' && !silent}
            <div class="needle" aria-hidden="true"></div>
        {/if}
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
    /* The strip is a focusable slider (tabindex/role) so clicking or arrowing
       it focuses the container; suppress the browser's ring around the WHOLE
       strip — the active cell's accent border already marks position. */
    .filmstrip:focus,
    .filmstrip:focus-visible {
        outline: none;
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
    /* Snap mode glides whole-ayah hops, so it gets a longer, more dramatic
       slide-and-settle (ease-out-expo) than hybrid's quick release snap. */
    .track.snap-glide.animate {
        transition: transform 560ms cubic-bezier(0.16, 1, 0.3, 1);
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
    /* Frozen cell — the verse held under a silence pause. De-accented (the
     *  highlight drops) but keeps its partial fill so the bar reads "held, not
     *  finished" until recitation regenerates. */
    .cell.frozen {
        border-color: var(--border-default);
    }
    /* Snap-mode cursor cell — the ayah under the invisible needle (active cell
     *  while playing, drag target while scrubbing). An inset accent ring keeps it
     *  distinct from `.active`'s tinted fill so both can show at once mid-drag. */
    .cell.cursor {
        border-color: var(--accent);
        box-shadow: inset 0 0 0 1px var(--accent);
    }
    /* Progress-bar hover preview — the verse recited at the hovered time. */
    .cell.preview {
        border-color: var(--accent-strong);
        border-style: dashed;
        background: var(--accent-tint);
    }
    .cell.preview .cell-num {
        color: var(--accent-strong);
    }
    .cell-fill {
        position: absolute;
        inset: 0 auto 0 0;
        width: 0;
        background: var(--accent-tint);
        pointer-events: none;
    }
    /* Active + frozen cells read the per-frame fill var (written by the driver);
       the frozen one simply holds the last value. */
    .cell.active .cell-fill,
    .cell.frozen .cell-fill {
        width: var(--cell-active-fill, 0%);
    }
    .cell.reached .cell-fill {
        width: 100%;
        background: var(--accent-tint-soft);
    }
    /* Eased fill ONLY during a loopback/seek glide — never a permanent
       transition (that would lag every forward-play frame). */
    .cell.active .cell-fill.glide {
        transition: width var(--t-base, 200ms) var(--ease-out-quart, ease);
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
        .track.animate,
        .track.snap-glide.animate,
        .cell.active .cell-fill.glide {
            transition: none;
        }
    }
</style>
