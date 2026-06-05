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
     * recitation-driven path. Scroll moves split by kind so they never fight:
     *   - Continuous playback (hybrid/tuner) tracks the LIVE recited position
     *     each frame via `stepScroll` — instant in forward play, and on a
     *     loopback/seek a per-frame catch-up that chases the still-moving target
     *     (never freezes on a stale snapshot). Scroll, fill and audio stay locked.
     *   - Discrete moves to a FIXED point (snap-center, click, key, drag-release,
     *     paused refresh) run through ONE JS tween (`glideTo`) with distance-
     *     proportional duration + ease-in-out, so a one-cell hop and a far scroll
     *     feel like the same motion. Live drag writes `offset` directly.
     * Surface-agnostic: fed `units` + a prebuilt `FilmstripModel` + a time
     * accessor + an onSeek cb.
     */
    import { type RecitationAnimConfig } from './config';
    import type { FilmstripModel } from './filmstrip-model';
    import { stepScroll } from './filmstrip-scroll';
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

    // ---- scroll-glide tuning (distance-proportional, single feel everywhere) ----
    /** ms per px of scroll distance — the glide's velocity (↑ = slower). */
    const GLIDE_MS_PER_PX = 0.9;
    /** Floor so a tiny hop is still a visible glide, not a snap. */
    const GLIDE_MIN_MS = 300;
    /** Cap so a full-film seek stays a smooth scroll-through, not endless. */
    const GLIDE_MAX_MS = 1500;
    /** An audio-time jump beyond this in one frame ⇒ a seek (glide), not the
     *  normal forward creep of playback. */
    const SEEK_JUMP_MS = 400;

    let containerEl = $state<HTMLDivElement | undefined>(undefined);
    let cw = $state(0); // container width
    let offset = $state(0); // px scrolled into the cells region (needle position)
    let dragging = $state(false);

    // Recitation-driven playback state (written by the rAF driver / refresh).
    let activeIdx = $state(-1); // cell of the recited word; holds during silence
    let cellFrac = $state(0); // word-proportional fill of the active cell
    let silent = $state(false); // in a silence gap → frozen, no highlight/cursor
    let frozenIdx = $state(-1); // last active cell, held while silent
    let jumping = $state(false); // mid-glide → cell-fill eases too
    let following = false; // continuous mode: smoothing offset toward live target
    let followTarget = 0; // last catch-up target — feeds stepScroll's velocity landing
    let lastActiveUnit = -1; // O(1) fast-path hint for findActiveAt
    let lastTimeMs = -1; // previous frame's audio time, for seek detection
    let fillGlideTimer: ReturnType<typeof setTimeout> | null = null;

    // JS scroll tween for DISCRETE moves to a fixed point (snap-center, click,
    // key, drag-release, paused refresh). Distance-proportional duration + soft
    // ease, so a one-cell hop and a far scroll feel like the same motion, just
    // longer. Continuous playback tracking does NOT use this (it would snapshot a
    // stale target); it tracks the live position via `stepScroll` instead.
    interface Tween { from: number; to: number; startT: number; dur: number; }
    let tween: Tween | null = null;
    let tweenRaf = 0;
    const reducedMotion = typeof matchMedia === 'function'
        && matchMedia('(prefers-reduced-motion: reduce)').matches;
    // ease-in-out sine — soft start AND stop (the old ease-out started abruptly).
    const easeInOut = (p: number): number => 0.5 - Math.cos(Math.PI * p) / 2;

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

    // ---- scroll tween: the one animated path that moves `offset` ----
    function stepTween(now: number): void {
        const t = tween;
        if (!t) { tweenRaf = 0; return; }
        const p = clamp(0, 1, (now - t.startT) / t.dur);
        offset = t.from + (t.to - t.from) * easeInOut(p);
        if (p >= 1) { tween = null; tweenRaf = 0; return; }
        tweenRaf = requestAnimationFrame(stepTween);
    }
    /** Distance-proportional glide duration (clamped). The shared "feel". */
    function glideDur(dist: number): number {
        return clamp(GLIDE_MIN_MS, dist * GLIDE_MS_PER_PX, GLIDE_MAX_MS);
    }
    /** Animate `offset` to a target — the one animated path for every deliberate
     *  strip scroll (click, key, snap-center, loopback, seek). Strip only. */
    function glideTo(target: number): void {
        target = clamp(0, lastRight, target);
        const dist = Math.abs(target - offset);
        if (reducedMotion || dist < 1) {
            tween = null;
            offset = target;
            return;
        }
        tween = { from: offset, to: target, startT: performance.now(), dur: glideDur(dist) };
        if (!tweenRaf) tweenRaf = requestAnimationFrame(stepTween);
    }
    function cancelTween(): void {
        tween = null;
        if (tweenRaf) cancelAnimationFrame(tweenRaf);
        tweenRaf = 0;
        following = false; // drop any continuous catch-up too
        followTarget = 0;
    }
    /** Ease the active cell's fill bar across a SINGLE loopback/seek rewind, then
     *  drop the transition so subsequent forward frames track instantly. The
     *  transition is short and one-shot — holding it across the whole glide would
     *  make every per-frame `setFill` chase a moving target and visibly lag the
     *  audio (the fill would crawl, never catching up). */
    function armFillGlide(dur: number): void {
        if (reducedMotion) return;
        containerEl?.style.setProperty('--cell-glide-dur', dur + 'ms');
        jumping = true;
        if (fillGlideTimer) clearTimeout(fillGlideTimer);
        // One eased step is ~one transition; clear once it has landed so forward
        // play is instant again. `disarmFillGlide` also clears it on the next
        // non-jump frame, whichever comes first.
        fillGlideTimer = setTimeout(() => { jumping = false; }, dur);
    }
    /** Drop the eased-fill transition the moment forward tracking resumes, so a
     *  loopback's eased rewind never bleeds into the live per-frame fill. */
    function disarmFillGlide(): void {
        if (!jumping) return;
        jumping = false;
        if (fillGlideTimer) { clearTimeout(fillGlideTimer); fillGlideTimer = null; }
    }
    /** A discrete strip move (loopback / seek / user nav): glide the strip AND
     *  ease the fill over the same distance-proportional time. */
    function jumpTo(target: number): void {
        armFillGlide(glideDur(Math.abs(clamp(0, lastRight, target) - offset)));
        glideTo(target);
    }

    /** A recitation discontinuity (loopback / seek) vs a smooth advance. */
    function isJump(prevIdx: number, newIdx: number, prevFrac: number, newFrac: number): boolean {
        if (prevIdx < 0) return false; // first activation — no glide
        if (newIdx < prevIdx) return true; // back to an earlier verse
        if (newIdx - prevIdx > JUMP_CELL_GAP) return true; // forward verse skip
        if (newIdx === prevIdx && newFrac < prevFrac - JUMP_FRAC_EPS) return true; // word loopback
        return false;
    }

    /** One rAF step of recitation-driven playback. */
    function drivePlayback(): void {
        const nowMs = getTimeMs();
        const tSec = (nowMs + config.leadMs) / 1000;
        const r = recitationAt(tSec, lastActiveUnit);
        // A large audio-time jump in one frame is a seek (e.g. a linear-bar
        // click), not the normal forward creep — glide to it like any other.
        const seeked = lastTimeMs >= 0 && Math.abs(nowMs - lastTimeMs) > SEEK_JUMP_MS;
        lastTimeMs = nowMs;
        if (!r) {
            // Silence: freeze — hold offset + fill, drop highlight/cursor. The
            // last active cell (frozenIdx) stays as a de-accented, held bar.
            silent = true;
            return;
        }
        const prevIdx = activeIdx;
        const prevFrac = cellFrac;
        lastActiveUnit = r.unitIdx;
        const discont = seeked || isJump(prevIdx, r.idx, prevFrac, r.frac);
        silent = false;
        activeIdx = r.idx;
        cellFrac = r.frac;
        frozenIdx = r.idx;
        setFill(r.frac);

        const snap = config.filmstripMotion === 'snap';
        const target = snap ? offsetForCellCenter(r.idx) : offsetForReci(r);

        if (snap) {
            // Snap centers the active cell — a fixed point, not a moving one, so
            // a one-shot glide is correct. Loopback/seek eases the fill too.
            if (discont) jumpTo(target);
            else { disarmFillGlide(); if (r.idx !== prevIdx) glideTo(target); }
            return;
        }

        // Hybrid/tuner continuously center the LIVE recited position. `stepScroll`
        // tracks it instantly in forward play, and on a loopback/seek arms a
        // smooth catch-up that chases the moving target (never a stale snapshot),
        // so scroll, fill and audio stay locked together. A discontinuity also
        // eases the fill once.
        if (discont) armFillGlide(GLIDE_MIN_MS);
        else disarmFillGlide();
        const wasFollowing = following;
        if (tween) cancelTween(); // a paused-refresh glide can't co-own offset
        const s = stepScroll(
            offset, target, discont, wasFollowing, followTarget, lastRight, reducedMotion,
        );
        offset = s.offset;
        following = s.following;
        followTarget = s.prevTarget;
    }

    // rAF while playing: drive the recitation mapping (all modes).
    $effect(() => {
        if (!playing) return;
        lastTimeMs = -1; // don't read the first frame as a seek
        let raf = 0;
        const loop = (): void => {
            if (!dragging && scrubMs == null) drivePlayback();
            raf = requestAnimationFrame(loop);
        };
        raf = requestAnimationFrame(loop);
        return () => cancelAnimationFrame(raf);
    });

    // Progress-bar drag → scroll-follow the dragged time (both motion modes).
    // Maps the time through the recitation timeline so it tracks the recited
    // position (correct under overlap/repeats). Direct follow (no glide) — you're
    // scrubbing live. Silence in the scrub → hold (no move).
    $effect(() => {
        if (scrubMs == null || cw === 0) return;
        cancelTween();
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
        lastTimeMs = -1;
        cancelTween();
        if (fillGlideTimer) clearTimeout(fillGlideTimer);
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
        cancelTween(); // the drag owns offset now
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
                glideTo(offsetForCellCenter(i));
                onSeek(seekMsForCell(i));
            }
        }
    }
    function clickToSeek(clientX: number): void {
        if (!containerEl) return;
        const i = cellAtClientX(clientX);
        if (i < 0) return;
        glideTo(offsetForCellCenter(i));
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
        lastTimeMs = -1; // resync; the next playing frame isn't a seek
        setFill(r.frac);
        jumpTo(config.filmstripMotion === 'snap'
            ? offsetForCellCenter(r.idx)
            : offsetForReci(r));
    }

    /** Force the new chapter's first ayah into view before audio canplay. */
    export function showFirstAyah(): void {
        if (!cells.length) return;
        activeIdx = -1;
        cellFrac = 0;
        silent = false;
        frozenIdx = -1;
        lastActiveUnit = -1;
        lastTimeMs = -1;
        cancelTween();
        containerEl?.style.removeProperty('--cell-active-fill');
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
                // Anchor on the cell recited at the LIVE audio position, not the
                // (possibly frozen/stale) `activeIdx` — inside a dropped re-take
                // the active cell can lag, and ±1 off it would skip verses.
                const live = cellViaTime(getTimeMs());
                const base = live >= 0 ? live : (activeIdx < 0 ? 0 : activeIdx);
                const i = clamp(0, cells.length - 1, base + d);
                glideTo(offsetForCellCenter(i));
                onSeek(seekMsForCell(i));
            }
        }}
    >
        <div
            class="track"
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
    /* The transform is driven imperatively by the JS scroll tween (`glideTo`),
       so the track carries NO CSS transition — every scroll, near or far, runs
       through one distance-proportional, ease-in-out animation. */
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
       transition (that would lag every forward-play frame). Duration is shared
       with the strip scroll (`--cell-glide-dur`) so bar + scroll move as one. */
    .cell.active .cell-fill.glide {
        transition: width var(--cell-glide-dur, 320ms) ease-in-out;
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
    /* The strip scroll is JS-driven and already skips the tween under reduced
       motion (`reducedMotion` in glideTo); kill the fill-glide transition too. */
    @media (prefers-reduced-motion: reduce) {
        .cell.active .cell-fill.glide {
            transition: none;
        }
    }
</style>
