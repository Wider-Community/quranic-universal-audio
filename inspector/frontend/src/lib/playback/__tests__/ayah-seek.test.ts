import { describe, expect, it } from 'vitest';

import { adjacentAyahStartFromIndex, adjacentAyahStartMs } from '../ayah-seek';

/**
 * Ayah-boundary seek targets. The position-based `adjacentAyahStartMs` infers
 * the current verse from start ordering, which is WRONG inside a re-take whose
 * audio plays past a later verse's canonical start; `adjacentAyahStartFromIndex`
 * takes the recitation-resolved current index for an exact step (the #143
 * footer-skip fix).
 */

// nasser_al_qatami chapter 102 canonical ayah starts (ms), ascending.
const STARTS = [240, 2250, 8910, 14_170, 37_600, 47_550, 51_660, 75_860];
//                102:1 102:2 102:3  102:4   102:5   102:6   102:7   102:8

describe('adjacentAyahStartMs (position-based)', () => {
    it('skips during a re-take: at 90s the playhead reads as the later verse', () => {
        // Audio is reciting 102:7's re-take (~86.2-93.0s), but 102:8's canonical
        // start (75.86s) is below 90s, so position-inference lands on 102:8.
        const ci = STARTS.filter((s) => s <= 90_000 + 1).length - 1;
        expect(STARTS[ci]).toBe(75_860); // → 102:8 (wrong; audio is in 102:7)
        // Forward from "102:8" → nothing → null (the footer then nudges +15s).
        expect(adjacentAyahStartMs(STARTS, 90_000, 1)).toBeNull();
    });
});

describe('adjacentAyahStartFromIndex (recitation-anchored)', () => {
    it('forward from a known re-take index lands exactly one verse ahead', () => {
        // Resolver says the playhead at 90s is reciting 102:7 (index 6).
        expect(adjacentAyahStartFromIndex(STARTS, 6, 90_000, 1)).toBe(75_860); // → 102:8
    });

    it('forward from the last verse returns null', () => {
        expect(adjacentAyahStartFromIndex(STARTS, 7, 100_000, 1)).toBeNull();
    });

    it('back restarts the current verse when >restartMs into it (re-take included)', () => {
        // 90s is ~38s into 102:7 (canonical start 51.66s) → restart 102:7.
        expect(adjacentAyahStartFromIndex(STARTS, 6, 90_000, -1)).toBe(51_660);
    });

    it('back drops to the previous verse when just inside the current one', () => {
        // 52s is <1.5s into 102:7 → previous verse 102:6.
        expect(adjacentAyahStartFromIndex(STARTS, 6, 52_000, -1)).toBe(47_550);
    });

    it('back from the first verse clamps to its start', () => {
        expect(adjacentAyahStartFromIndex(STARTS, 0, 500, -1)).toBe(240);
    });

    it('returns null for an out-of-range index', () => {
        expect(adjacentAyahStartFromIndex(STARTS, -1, 1000, 1)).toBeNull();
        expect(adjacentAyahStartFromIndex(STARTS, 99, 1000, 1)).toBeNull();
    });
});
