import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import AyahFilmstrip from '../AyahFilmstrip.svelte';
import { DEFAULT_RECITATION_CONFIG } from '../config';
import { buildFilmstripModel } from '../filmstrip-model';
import type { AnimUnit, TimeSpan } from '../types';

/**
 * Component guard for a mid-verse uneven re-take (loopback "type 1").
 *
 * When the reciter loops back and re-recites only SOME of a verse's words at an
 * uneven pace (word 3 fast, word 4 slow), the cursor must cross the re-recited
 * span at ONE constant velocity that conforms to the re-take's OWN duration — it
 * must NOT lurch word-by-word (fast then slow) the way tracking each word's
 * canonical fraction would. The covered half of the cell (40px) is crossed over
 * the 3s re-take ≈ 13px/s, steady throughout.
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

const PX_PER_SEC = 20; // verse 1 (4s canonical) → an 80px cell; re-take covers its right half
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

describe('AyahFilmstrip mid-verse uneven re-take (constant in-cell velocity)', () => {
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

    it('crosses the unevenly-replayed span at one steady velocity, no per-word lurch', async () => {
        const { container } = render(AyahFilmstrip, {
            units, model, durationMs: 8000, getTimeMs, playing: true, config, onSeek: () => {},
        });
        await tick();

        // Forward take, then loop back into the verse just after t=4s.
        for (const ms of [500, 1500, 2500, 3900]) await step(ms);

        // Fine-step (≈real rAF cadence) through the loopback + replay so the eased
        // back-hop converges; sample the settled window.
        const off: Record<number, number> = {};
        const marks = new Set([5200, 5950, 6700]);
        for (let ms = 4000; ms <= 6700; ms += 50) {
            await step(ms);
            if (marks.has(ms)) off[ms] = scrollOffset(container);
        }

        // Moves forward through the replay, not frozen.
        expect(off[6700]!).toBeGreaterThan(off[5200]! + 5);

        // ONE steady velocity conforming to the re-take: the covered half of the
        // 80px cell (40px) crossed over the 3s re-take ≈ 13px/s. Tracking each word's
        // canonical fraction instead would lurch — word 3 (20px / 0.5s = 40px/s) then
        // word 4 (20px / 2.5s = 8px/s) — the regression this guards.
        const vAll = (off[6700]! - off[5200]!) / 1.5;
        expect(vAll).toBeGreaterThan(11);
        expect(vAll).toBeLessThan(16);

        // …and that velocity is constant across the window (no acceleration).
        const firstHalf = off[5950]! - off[5200]!;
        const secondHalf = off[6700]! - off[5950]!;
        expect(Math.abs(firstHalf - secondHalf)).toBeLessThan(3);
    });
});
