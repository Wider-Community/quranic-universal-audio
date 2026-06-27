import { describe, expect, it } from 'vitest';

import { buildFilmstripModel } from '../filmstrip-model';
import type { AnimUnit, TimeSpan } from '../types';

/** Build a unit; the LAST occurrence interval optionally carries the waṣl flag
 *  (mirrors what `buildChapterRecitation` stamps on a bridging take's last word). */
function unitW(
    location: string,
    intervals: Array<[number, number]>,
    wasl?: { to: string; dynamic?: boolean },
): AnimUnit {
    const [surahRaw, ayahRaw, wordRaw] = location.split(':');
    const surah = Number(surahRaw);
    const ayah = Number(ayahRaw);
    const spans: TimeSpan[] = intervals.map(([start, end]) => ({ start, end }));
    if (wasl && spans.length) {
        const last = spans[spans.length - 1]!;
        last.waslTo = wasl.to;
        last.waslDynamic = wasl.dynamic ?? false;
    }
    return {
        location, ayahKey: `${surah}:${ayah}`, surah, ayah, word: Number(wordRaw),
        text: location, start: spans[0]!.start, end: spans[spans.length - 1]!.end,
        intervals: spans, letters: [],
    };
}

describe('buildFilmstripModel — waṣl merge flags', () => {
    it('marks a static chain: every internal boundary bridges, none dynamic', () => {
        const cells = buildFilmstripModel([
            unitW('20:25:1', [[0, 1]]),
            unitW('20:25:4', [[1, 2]], { to: '20:26' }),
            unitW('20:26:1', [[2, 3]]),
            unitW('20:26:5', [[3, 4]], { to: '20:27' }),
            unitW('20:27:1', [[4, 5]]),
        ], 'duration').cells;
        expect(cells.map((c) => c.waslNext)).toEqual([true, true, false]);
        expect(cells.every((c) => !c.waslDynamic)).toBe(true);
    });

    it('flags a dynamic boundary (the bridging take is dynamic)', () => {
        const cells = buildFilmstripModel([
            unitW('14:1:1', [[0, 1]]),
            unitW('14:1:16', [[1, 2]], { to: '14:2', dynamic: true }),
            unitW('14:2:1', [[2, 3]]),
        ], 'duration').cells;
        expect(cells[0]!.waslNext).toBe(true);
        expect(cells[0]!.waslDynamic).toBe(true);
        expect(cells[1]!.waslNext).toBe(false);
    });

    it('no-ops on a v9 chapter (no waslTo anywhere)', () => {
        const cells = buildFilmstripModel([
            unitW('2:5:1', [[0, 1]]),
            unitW('2:6:1', [[1, 2]]),
        ], 'duration').cells;
        expect(cells.every((c) => !c.waslNext && !c.waslDynamic)).toBe(true);
    });

    it('only bridges into the IMMEDIATELY-next present verse (not a far waslTo)', () => {
        // A stray waslTo that doesn't match the next cell's key must not merge.
        const cells = buildFilmstripModel([
            unitW('5:1:1', [[0, 1]], { to: '5:9' }), // points past the next verse
            unitW('5:2:1', [[1, 2]]),
        ], 'duration').cells;
        expect(cells[0]!.waslNext).toBe(false);
    });

    it('placeholder cells never merge', () => {
        const coverage = {
            numVerses: 3,
            status: new Map<number, 'words' | 'full'>([[2, 'full']]),
            missingWords: new Map<number, number[]>(),
        };
        const cells = buildFilmstripModel([
            unitW('1:1:1', [[0, 2]]),
            unitW('1:3:1', [[5, 6]]),
        ], 'duration', coverage).cells;
        const placeholder = cells[1]!;
        expect(placeholder.missing).toBe('full');
        expect(placeholder.waslNext).toBe(false);
    });
});
