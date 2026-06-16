import { describe, expect, it } from 'vitest';

import { buildFilmstripModel } from '../filmstrip-model';
import type { AnimUnit, TimeSpan } from '../types';

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

// One verse, 3 words of canonical duration 1s / 2s / 1s. Word 2 is ALSO recited
// again much later (a loopback) — its second occurrence must not inflate widths.
const verse = [
    unit('1:1:1', [[0, 1]]),
    unit('1:1:2', [[1, 3], [10, 12]]),
    unit('1:1:3', [[3, 4]]),
];

describe('buildFilmstripModel canonDurSec', () => {
    it('sizes the cell by canonical first-occurrence durations, not the loopback', () => {
        const model = buildFilmstripModel(verse, 'duration');
        // 1 + 2 + 1 = 4s; a naive max(end)-min(start) would read 12s.
        expect(model.cells[0]!.canonDurSec).toBeCloseTo(4, 6);
    });

    it('exposes the verse canonical start as the seek target', () => {
        const model = buildFilmstripModel(verse, 'duration');
        expect(model.cells[0]!.canonStartSec).toBeCloseTo(0, 6);
    });
});

describe('buildFilmstripModel word fractions', () => {
    it('weights word bands by duration (1/2/1 → quarters)', () => {
        const words = buildFilmstripModel(verse, 'duration').cells[0]!.words;
        expect(words.map((w) => w.frac0)).toEqual([0, 0.25, 0.75]);
        expect(words.map((w) => w.frac1)).toEqual([0.25, 0.75, 1]);
    });

    it('weights word bands equally when asked (1/3 each)', () => {
        const words = buildFilmstripModel(verse, 'equal').cells[0]!.words;
        expect(words[0]!.frac1).toBeCloseTo(1 / 3, 6);
        expect(words[1]!.frac1).toBeCloseTo(2 / 3, 6);
        expect(words[2]!.frac1).toBeCloseTo(1, 6);
    });
});

describe('buildFilmstripModel nextGapSec', () => {
    it('measures between-verse silence from canonical end to the next start', () => {
        const units = [
            unit('1:1:1', [[0, 1]]),
            unit('1:1:2', [[1, 2]]), // verse 1 canonical end = 2
            unit('1:2:1', [[3, 4]]), // verse 2 starts at 3 → 1s pause
            unit('1:3:1', [[4, 5]]), // verse 3 starts at 4 → contiguous (0)
        ];
        const cells = buildFilmstripModel(units, 'duration').cells;
        expect(cells[0]!.nextGapSec).toBeCloseTo(1, 6);
        expect(cells[1]!.nextGapSec).toBeCloseTo(0, 6);
        expect(cells[2]!.nextGapSec).toBeCloseTo(0, 6); // last cell — no next
    });

    it('skips unrecited placeholders when measuring the gap to the next present verse', () => {
        const units = [
            unit('1:1:1', [[0, 2]]), // verse 1 end = 2
            unit('1:3:1', [[5, 6]]), // verse 3 starts at 5 (verse 2 fully missing)
        ];
        const coverage = {
            numVerses: 3,
            status: new Map<number, 'words' | 'full'>([[2, 'full']]),
            missingWords: new Map<number, number[]>(),
        };
        const cells = buildFilmstripModel(units, 'duration', coverage).cells;
        // cells: [verse1, placeholder verse2, verse3]; gap skips the placeholder.
        expect(cells[0]!.nextGapSec).toBeCloseTo(3, 6);
        expect(cells[1]!.nextGapSec).toBe(0); // placeholder carries no silence
    });
});

describe('buildFilmstripModel lookups', () => {
    it('maps every unit to its verse cell across two verses', () => {
        const units = [
            unit('1:1:1', [[0, 1]]),
            unit('1:1:2', [[1, 2]]),
            unit('1:2:1', [[2, 3]]),
        ];
        const model = buildFilmstripModel(units, 'duration');
        expect(Array.from(model.cellOfUnit)).toEqual([0, 0, 1]);
        expect(model.indexByAyahKey.get('1:1')).toBe(0);
        expect(model.indexByAyahKey.get('1:2')).toBe(1);
    });

    it('returns an empty model for no units', () => {
        const model = buildFilmstripModel([], 'duration');
        expect(model.cells).toEqual([]);
        expect(model.cellOfUnit.length).toBe(0);
    });
});

describe('buildFilmstripModel coverage merge', () => {
    // Verses 1 (words 1,2) and 3 (word 1) recited; verses 2 and 4 fully missing;
    // verse 1 is missing word 3.
    const units = [
        unit('1:1:1', [[0, 1]]),
        unit('1:1:2', [[1, 2]]),
        unit('1:3:1', [[2, 3]]),
    ];
    const coverage = {
        numVerses: 4,
        status: new Map<number, 'words' | 'full'>([[1, 'words'], [2, 'full'], [4, 'full']]),
        missingWords: new Map<number, number[]>([[1, [3]]]),
    };

    it('inserts placeholder cells for fully-missing verses in ayah order', () => {
        const model = buildFilmstripModel(units, 'duration', coverage);
        expect(model.cells.map((c) => c.ayah)).toEqual([1, 2, 3, 4]);
        expect(model.cells.map((c) => c.missing)).toEqual(['words', 'full', 'none', 'full']);
    });

    it('placeholder cells carry no geometry or units', () => {
        const ph = buildFilmstripModel(units, 'duration', coverage).cells[1]!;
        expect(ph.canonDurSec).toBe(0);
        expect(ph.words).toEqual([]);
        expect(ph.unitStart).toBe(-1);
    });

    it('remaps cellOfUnit + indexByAyahKey to the merged indices', () => {
        const model = buildFilmstripModel(units, 'duration', coverage);
        // verse 1 units → cell 0; verse 3 unit → cell 2 (placeholders shift it).
        expect(Array.from(model.cellOfUnit)).toEqual([0, 0, 2]);
        expect(model.indexByAyahKey.get('1:3')).toBe(2);
        expect(model.indexByAyahKey.get('1:4')).toBe(3);
    });

    it('tags every cell none without coverage (back-compat)', () => {
        const model = buildFilmstripModel(units, 'duration');
        expect(model.cells.map((c) => c.missing)).toEqual(['none', 'none']);
    });
});
