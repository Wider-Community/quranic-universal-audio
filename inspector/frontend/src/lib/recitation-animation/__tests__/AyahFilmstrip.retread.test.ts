import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import AyahFilmstrip from '../AyahFilmstrip.svelte';
import { DEFAULT_RECITATION_CONFIG } from '../config';
import { buildFilmstripModel } from '../filmstrip-model';
import type { AnimUnit, TimeSpan } from '../types';

/**
 * Component guard for the constant-velocity loopback re-tread.
 *
 * When the reciter loops back and re-recites, the replay's pace differs from the
 * first take, so tracking each replayed word's canonical offset would vary the
 * scroll speed word-by-word. The re-tread instead crosses the repeated span at
 * ONE velocity. This fixture loops back mid-verse (type 1) with a deliberately
 * UNEVEN replay (word 3 fast, word 4 slow); the strip must still scroll at the
 * steady ruler velocity, not 3× then ⅓×.
 */

function unit(loc: string, ivs: Array<[number, number]>): AnimUnit {
    const [s, a, w] = loc.split(':').map(Number);
    const spans: TimeSpan[] = ivs.map(([st, en]) => ({ start: st, end: en }));
    return {
        location: loc, ayahKey: `${s}:${a}`, surah: s!, ayah: a!, word: w!, text: loc,
        start: spans[0]!.start, end: spans[spans.length - 1]!.end, intervals: spans, letters: [],
    };
}

// Verse 1 (4 one-second words) recited forward, then looped back to word 3 and
// re-recited UNEVENLY — word 3 fast (0.5s), word 4 slow (2.5s) — before verse 2.
const units: AnimUnit[] = [
    unit('1:1:1', [[0, 1]]),
    unit('1:1:2', [[1, 2]]),
    unit('1:1:3', [[2, 3], [4, 4.5]]),
    unit('1:1:4', [[3, 4], [4.5, 7]]),
    unit('1:2:1', [[7, 8]]),
];
const model = buildFilmstripModel(units, 'duration');

const PX_PER_SEC = 20; // verse 1 (4s canonical) → an 80px cell; ruler velocity 20px/s
const config = {
    ...DEFAULT_RECITATION_CONFIG,
    filmstripMotion: 'hybrid' as const,
    filmstripPxPerSec: PX_PER_SEC,
    leadMs: 0,
};

function scrollOffset(container: HTMLElement): number {
    const el = container.querySelector<HTMLElement>('.track');
    const m = el ? /translateX\((-?[\d.]+)px\)/.exec(el.style.transform) : null;
    return m ? -parseFloat(m[1]!) : 0;
}

describe('AyahFilmstrip loopback re-tread (constant velocity)', () => {
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

    it('crosses the unevenly-replayed span at the steady ruler velocity', async () => {
        const { container } = render(AyahFilmstrip, {
            units, model, durationMs: 8000, getTimeMs, playing: true, config, onSeek: () => {},
        });
        await tick();

        // Forward take, then loop back into the verse just after t=4s.
        for (const ms of [500, 1500, 2500, 3900]) await step(ms);

        // Fine-step (≈real rAF cadence) through the loopback + replay so the eased
        // back-hop converges onto the ramp; sample the settled window.
        const off: Record<number, number> = {};
        const marks = new Set([5200, 5950, 6700]);
        for (let ms = 4000; ms <= 6700; ms += 50) {
            await step(ms);
            if (marks.has(ms)) off[ms] = scrollOffset(container);
        }

        // Moves forward through the replay, not frozen.
        expect(off[6700]!).toBeGreaterThan(off[5200]! + 20);

        // Holds the ruler velocity (~20px/s). Tracking the live replay instead
        // would read ~7px/s here (word 4 replayed over 2.5s) — the lurch we fixed.
        const vAll = (off[6700]! - off[5200]!) / 1.5;
        expect(vAll).toBeGreaterThan(16);
        expect(vAll).toBeLessThan(24);

        // …and that velocity is consistent across the window (no acceleration).
        const firstHalf = off[5950]! - off[5200]!;
        const secondHalf = off[6700]! - off[5950]!;
        expect(Math.abs(firstHalf - secondHalf)).toBeLessThan(6);
    });
});
