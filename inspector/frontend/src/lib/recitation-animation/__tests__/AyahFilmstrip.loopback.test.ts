import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import AyahFilmstrip from '../AyahFilmstrip.svelte';
import { DEFAULT_RECITATION_CONFIG } from '../config';
import { buildFilmstripModel } from '../filmstrip-model';
import type { AnimUnit, TimeSpan } from '../types';

/**
 * Component-level guard for the recitation-driven filmstrip loopback.
 *
 * Two regressions are covered:
 *   1. The active cell + fill must travel BACK to the looped verse and re-light it
 *      — never stay stuck/frozen on the later verse "as if pausing like silence".
 *   2. The STRIP SCROLL must track the re-recited word through the WHOLE replay
 *      window, not just the jump moment. The earlier fixed-fraction catch-up
 *      settled at a constant lag against the still-moving target, so the strip
 *      trailed the audio (sitting in the wrong cell's region) for the entire
 *      loopback and only realigned once linear forward play resumed. The
 *      velocity-aware landing must keep the offset on the live recited position.
 *
 * (The pure per-frame scroll stepper is unit-tested in `filmstrip-scroll.test.ts`.)
 */

function unit(loc: string, ivs: Array<[number, number]>): AnimUnit {
    const [s, a, w] = loc.split(':').map(Number);
    const spans: TimeSpan[] = ivs.map(([st, en]) => ({ start: st, end: en }));
    return {
        location: loc, ayahKey: `${s}:${a}`, surah: s!, ayah: a!, word: w!, text: loc,
        start: spans[0]!.start, end: spans[spans.length - 1]!.end, intervals: spans, letters: [],
    };
}

// v1 (2 words) · v2 (2 words, RECITED then LOOPED BACK at 6-8s) · v3 (2 words).
const units: AnimUnit[] = [
    unit('1:1:1', [[0, 1]]),
    unit('1:1:2', [[1, 2]]),
    unit('1:2:1', [[2, 3], [6, 7]]),
    unit('1:2:2', [[3, 4], [7, 8]]),
    unit('1:3:1', [[4, 5]]),
    unit('1:3:2', [[5, 6]]),
];
const model = buildFilmstripModel(units, 'duration');

function activeCellAyah(container: HTMLElement): number | null {
    const el = container.querySelector<HTMLElement>('.cell.active .cell-num');
    return el ? Number(el.textContent) : null;
}
function frozenCellAyah(container: HTMLElement): number | null {
    const el = container.querySelector<HTMLElement>('.cell.frozen .cell-num');
    return el ? Number(el.textContent) : null;
}
/** Current strip scroll offset (px) — the negated track translateX. */
function scrollOffset(container: HTMLElement): number {
    const el = container.querySelector<HTMLElement>('.track');
    const m = el ? /translateX\((-?[\d.]+)px\)/.exec(el.style.transform) : null;
    return m ? -parseFloat(m[1]!) : 0;
}
/** Each cell's [left, right] px span (cumBefore … cumBefore+width), gap-aware —
 *  so a test can assert the offset sits within a given verse's region. */
function cellSpans(container: HTMLElement, gapPx: number): Array<[number, number]> {
    const out: Array<[number, number]> = [];
    let cum = 0;
    for (const el of container.querySelectorAll<HTMLElement>('.cell')) {
        const w = parseFloat(el.style.width);
        out.push([cum, cum + w]);
        cum += w + gapPx;
    }
    return out;
}

describe('AyahFilmstrip loopback (recitation-driven)', () => {
    // Manual rAF + clock so the playback loop can be stepped frame-by-frame.
    let rafCbs: FrameRequestCallback[] = [];
    let nowMs = 0;
    const getTimeMs = (): number => nowMs;

    beforeEach(() => {
        rafCbs = [];
        vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback): number => {
            rafCbs.push(cb);
            return rafCbs.length;
        });
        vi.stubGlobal('cancelAnimationFrame', () => {});
        vi.spyOn(performance, 'now').mockImplementation(() => nowMs);
    });
    afterEach(() => {
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });

    /** Advance the audio clock to `toMs` and run the rAF loop to steady state for
     *  this frame. The playback loop re-queues itself each pump; draining the
     *  re-queued callback makes the offset reflect THIS frame's recited target
     *  (one pump would leave it a frame behind — the manual-clock analogue of the
     *  browser running exactly one rAF per displayed frame). */
    async function step(toMs: number): Promise<void> {
        nowMs = toMs;
        for (let i = 0; i < 2 && rafCbs.length; i++) {
            const batch = rafCbs;
            rafCbs = [];
            for (const cb of batch) cb(nowMs);
            await tick();
        }
    }

    it('travels the active cell back to the looped verse, never stuck/frozen', async () => {
        const { container } = render(AyahFilmstrip, {
            units, model, durationMs: 8000, getTimeMs, playing: true,
            config: { ...DEFAULT_RECITATION_CONFIG, filmstripMotion: 'hybrid' },
            onSeek: () => {},
        });
        await tick();

        // Forward play through verse 3 (later in the chapter).
        for (const ms of [500, 1500, 2500, 3500, 4500, 5500]) await step(ms);
        expect(activeCellAyah(container)).toBe(3);

        // Loopback: audio re-enters verse 2 (occurrence at 6-8s). The active cell
        // must travel BACK to verse 2 — not freeze on verse 3 or go silent.
        for (const ms of [6200, 6600, 7000]) await step(ms);
        expect(frozenCellAyah(container)).toBeNull(); // not stuck-as-silence
        expect(activeCellAyah(container)).toBe(2);
    });

    it('travels the strip scroll into the looped verse and tracks the re-recited word', async () => {
        const { container } = render(AyahFilmstrip, {
            units, model, durationMs: 8000, getTimeMs, playing: true,
            config: { ...DEFAULT_RECITATION_CONFIG, filmstripMotion: 'hybrid' },
            onSeek: () => {},
        });
        await tick();

        const gap = DEFAULT_RECITATION_CONFIG.filmstripGapPx;
        const spans = cellSpans(container, gap); // [left,right] px per cell
        const [v2Left, v2Right] = spans[1]!; // verse 2 cell region

        // Forward play to verse 3, then loop back to verse 2 (occurrence at 6-8s).
        for (const ms of [500, 1500, 2500, 3500, 4500, 5500]) await step(ms);
        const beforeLoop = scrollOffset(container);
        expect(beforeLoop).toBeGreaterThan(v2Right); // sitting past verse 2, on verse 3

        // Sample every frame across the replay. The strip must travel BACK into
        // verse 2's region and advance forward through it as the re-recited word
        // progresses. The earlier fixed-fraction catch-up trailed by a constant lag,
        // so it never reached verse 2 — it lingered at/past v2Right (on verse 3) for
        // the whole replay and only realigned after linear play resumed.
        const offs: number[] = [];
        for (let ms = 6050; ms <= 7950; ms += 100) {
            await step(ms);
            offs.push(scrollOffset(container));
        }

        // Lands inside verse 2 within a couple of frames and STAYS there.
        const landed = offs.slice(2);
        for (const off of landed) {
            expect(off).toBeGreaterThanOrEqual(v2Left - 2); // in verse 2…
            expect(off).toBeLessThanOrEqual(v2Right + 2); // …not drifted into verse 3
            expect(off).toBeLessThan(beforeLoop); // travelled back from the loop point
        }
        // …advancing monotonically as the replayed word progresses (never frozen).
        expect(landed[landed.length - 1]!).toBeGreaterThan(landed[0]! + 20);
    });
});
