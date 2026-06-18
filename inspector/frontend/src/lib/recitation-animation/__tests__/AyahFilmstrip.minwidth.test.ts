import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import AyahFilmstrip from '../AyahFilmstrip.svelte';
import { DEFAULT_RECITATION_CONFIG } from '../config';
import { buildFilmstripModel } from '../filmstrip-model';
import type { AnimUnit, TimeSpan } from '../types';

/**
 * Component guard for the min-cell-width floor + gap-absorption.
 *
 * A verse too short to earn a legible cell at `filmstripPxPerSec` is floored to
 * `filmstripMinCellPx` (visible width). The floor must NOT speed the cursor up
 * inside that verse: the cursor crosses only the verse's time-true span (`aw`,
 * centered), so its in-verse velocity stays the ruler `pxPerSec`. The floor's
 * surplus margin is instead absorbed into the adjacent between-verse gap, where
 * the silence already scrolls the (greyed) needle.
 */

function unit(loc: string, ivs: Array<[number, number]>): AnimUnit {
    const [s, a, w] = loc.split(':').map(Number);
    const spans: TimeSpan[] = ivs.map(([st, en]) => ({ start: st, end: en }));
    return {
        location: loc, ayahKey: `${s}:${a}`, surah: s!, ayah: a!, word: w!, text: loc,
        start: spans[0]!.start, end: spans[spans.length - 1]!.end, intervals: spans, letters: [],
    };
}

// A 0.5s verse (floors) then a 3s verse, with a 1.5s silence between.
const units: AnimUnit[] = [
    unit('7:1:1', [[0, 0.5]]),
    unit('7:2:1', [[2, 5]]),
];
const model = buildFilmstripModel(units, 'duration');

// pxPerSec=20, minCellPx=18 → verse 1: aw = 0.5×20 = 10px, floored to w = 18px
// (lead 4 each side); verse 2: aw = w = 60px; gap = 1.5s × 20 = 30px.
const PX_PER_SEC = 20;
const MIN_CELL = 18;
const config = {
    ...DEFAULT_RECITATION_CONFIG,
    filmstripMotion: 'hybrid' as const,
    filmstripPxPerSec: PX_PER_SEC,
    filmstripMinCellPx: MIN_CELL,
    leadMs: 0,
};

function cellWidths(container: HTMLElement): number[] {
    return [...container.querySelectorAll<HTMLElement>('.cell')].map((el) => parseFloat(el.style.width));
}
function scrollOffset(container: HTMLElement): number {
    const el = container.querySelector<HTMLElement>('.track');
    const m = el ? /translateX\((-?[\d.]+)px\)/.exec(el.style.transform) : null;
    return m ? -parseFloat(m[1]!) : 0;
}

describe('AyahFilmstrip min-width floor + gap absorption', () => {
    let rafCbs: FrameRequestCallback[] = [];
    let nowMs = 0;
    const getTimeMs = (): number => nowMs;

    beforeEach(() => {
        rafCbs = [];
        nowMs = 0;
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

    async function step(toMs: number): Promise<void> {
        nowMs = toMs;
        for (let i = 0; i < 2 && rafCbs.length; i++) {
            const batch = rafCbs;
            rafCbs = [];
            for (const cb of batch) cb(nowMs);
            await tick();
        }
    }

    it('floors a too-short verse to filmstripMinCellPx while leaving a long verse pure-time', async () => {
        const { container } = render(AyahFilmstrip, {
            units, model, durationMs: 5000, getTimeMs, playing: false, config, onSeek: () => {},
        });
        await tick();
        const [w1, w2] = cellWidths(container);
        expect(w1).toBe(MIN_CELL); // 0.5s × 20 = 10px → floored to 18
        expect(w2).toBe(60); // 3s × 20 = 60px, above the floor → untouched
    });

    it('keeps the in-verse cursor at the ruler velocity despite the floor', async () => {
        const { container } = render(AyahFilmstrip, {
            units, model, durationMs: 5000, getTimeMs, playing: true, config, onSeek: () => {},
        });
        await tick();

        await step(50); // frac 0.1 within verse 1
        const early = scrollOffset(container);
        await step(450); // frac 0.9 within verse 1
        const late = scrollOffset(container);

        // Crossing only the centered aw (10px over 0.5s) keeps velocity at the ruler
        // 20px/s. Crossing the full floored 18px would read ~36px/s (the lurch).
        const vel = (late - early) / ((450 - 50) / 1000);
        expect(vel).toBeGreaterThan(18);
        expect(vel).toBeLessThan(22);
    });

    it('absorbs the floor surplus into the between-verse silence scroll', async () => {
        const { container } = render(AyahFilmstrip, {
            units, model, durationMs: 5000, getTimeMs, playing: true, config, onSeek: () => {},
        });
        await tick();

        for (const ms of [50, 250, 450]) await step(ms); // play through verse 1
        const endOfV1 = scrollOffset(container); // ≈ cumBefore0 + (w+aw)/2 = 14

        await step(1250); // mid-silence (p≈0.5 of the 0.5→2s gap)
        const midGap = scrollOffset(container);

        // The needle leaves verse 1's active span and scrolls on toward verse 2's
        // active start (cell-2 cumBefore = 48), covering the absorbed margin + gap.
        expect(midGap).toBeGreaterThan(endOfV1);
        expect(midGap).toBeGreaterThan(20);
        expect(midGap).toBeLessThan(48);
    });
});
