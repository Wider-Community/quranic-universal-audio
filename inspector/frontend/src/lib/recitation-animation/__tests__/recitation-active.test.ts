import { describe, expect, it } from 'vitest';

import { buildSortedIntervals, findActiveAt } from '../recitation-active';
import type { AnimUnit, TimeSpan } from '../types';

/** Build a unit with explicit occurrence intervals (ascending). */
function unit(location: string, intervals: Array<[number, number]>): AnimUnit {
    const [surahRaw, ayahRaw, wordRaw] = location.split(':');
    const surah = Number(surahRaw);
    const ayah = Number(ayahRaw);
    const spans: TimeSpan[] = intervals.map(([start, end]) => ({ start, end }));
    return {
        location,
        ayahKey: `${surah}:${ayah}`,
        surah,
        ayah,
        word: Number(wordRaw),
        text: location,
        start: spans[0]!.start,
        end: spans[spans.length - 1]!.end,
        intervals: spans,
        letters: [],
    };
}

describe('buildSortedIntervals', () => {
    it('flattens every occurrence and sorts ascending by start', () => {
        const units = [
            unit('1:1:1', [[0, 1], [4, 5]]),
            unit('1:1:2', [[1, 2]]),
        ];
        const sorted = buildSortedIntervals(units);
        expect(sorted.map((s) => s.start)).toEqual([0, 1, 4]);
        expect(sorted.map((s) => s.unitIdx)).toEqual([0, 1, 0]);
    });

    it('returns an empty list for no units', () => {
        expect(buildSortedIntervals([])).toEqual([]);
    });
});

describe('findActiveAt', () => {
    const units = [
        unit('1:1:1', [[0, 1]]),
        unit('1:1:2', [[1, 2]]),
        unit('1:1:3', [[3, 4]]),
    ];
    const sorted = buildSortedIntervals(units);

    it('locates the next unit via the O(1) fast-path from the prior hint', () => {
        // last=0 (unit 1 was active); t is inside unit 2 — the [last, last+1]
        // fast-path should return it without falling back to bsearch.
        const hit = findActiveAt(units, sorted, 1.5, 0);
        expect(hit).toEqual({ unitIdx: 1, ivStart: 1, ivEnd: 2 });
    });

    it('returns null in a mid-recitation silence gap', () => {
        // [2,3) is a gap between unit 2 (ends 2) and unit 3 (starts 3).
        expect(findActiveAt(units, sorted, 2.5, 1)).toBeNull();
    });

    it('returns null before the first interval (leading silence)', () => {
        expect(findActiveAt(units, sorted, -0.5, -1)).toBeNull();
    });

    it('returns null after the last interval (trailing silence)', () => {
        expect(findActiveAt(units, sorted, 9, 2)).toBeNull();
    });

    it('travels back to an earlier verse on a loopback via bsearch fallback', () => {
        // Reading order A,B; A is repeated AFTER B. The forward hint points at B,
        // so the fast-path misses and bsearch must find A's later occurrence.
        const loop = [
            unit('1:1:1', [[0, 1], [4, 5]]),
            unit('1:1:2', [[1, 2]]),
        ];
        const loopSorted = buildSortedIntervals(loop);
        const hit = findActiveAt(loop, loopSorted, 4.5, 1);
        expect(hit).toEqual({ unitIdx: 0, ivStart: 4, ivEnd: 5 });
    });

    it('selects the occurrence interval that contains the time on a repeat', () => {
        const repeated = [unit('1:1:1', [[0, 1], [5, 6]])];
        const repeatedSorted = buildSortedIntervals(repeated);
        const hit = findActiveAt(repeated, repeatedSorted, 5.4, -1);
        expect(hit).toEqual({ unitIdx: 0, ivStart: 5, ivEnd: 6 });
    });

    it('returns null for no units', () => {
        expect(findActiveAt([], [], 1, -1)).toBeNull();
    });
});
