import { describe, expect, it } from 'vitest';

import type { AnimUnit, TimeSpan } from '../../recitation-animation/types';
import { computeChapterCoverage } from '../coverage';

function unit(location: string): AnimUnit {
    const [s, a, w] = location.split(':').map(Number) as [number, number, number];
    const spans: TimeSpan[] = [{ start: 0, end: 1 }];
    return {
        location,
        ayahKey: `${s}:${a}`,
        surah: s,
        ayah: a,
        word: w,
        text: location,
        start: 0,
        end: 1,
        intervals: spans,
        letters: [],
    };
}

// Chapter 1 reference: verse 1 = 3 words, verse 2 = 5, verse 3 = 4.
const refCounts = new Map<number, number>([[1, 3], [2, 5], [3, 4]]);

describe('computeChapterCoverage', () => {
    it('marks nothing when every verse is complete', () => {
        const units = [
            unit('1:1:1'), unit('1:1:2'), unit('1:1:3'),
            unit('1:2:1'), unit('1:2:2'), unit('1:2:3'), unit('1:2:4'), unit('1:2:5'),
            unit('1:3:1'), unit('1:3:2'), unit('1:3:3'), unit('1:3:4'),
        ];
        const cov = computeChapterCoverage(units, 1, refCounts);
        expect(cov.numVerses).toBe(3);
        expect(cov.status.size).toBe(0);
    });

    it('flags a present verse missing some words with the missing indices', () => {
        // verse 1 recites words 1 and 3 (missing 2); verses 2,3 complete.
        const units = [
            unit('1:1:1'), unit('1:1:3'),
            unit('1:2:1'), unit('1:2:2'), unit('1:2:3'), unit('1:2:4'), unit('1:2:5'),
            unit('1:3:1'), unit('1:3:2'), unit('1:3:3'), unit('1:3:4'),
        ];
        const cov = computeChapterCoverage(units, 1, refCounts);
        expect(cov.status.get(1)).toBe('words');
        expect(cov.missingWords.get(1)).toEqual([2]);
    });

    it('flags an unrecited verse as fully missing', () => {
        // verse 2 absent entirely.
        const units = [
            unit('1:1:1'), unit('1:1:2'), unit('1:1:3'),
            unit('1:3:1'), unit('1:3:2'), unit('1:3:3'), unit('1:3:4'),
        ];
        const cov = computeChapterCoverage(units, 1, refCounts);
        expect(cov.status.get(2)).toBe('full');
        expect(cov.missingWords.has(2)).toBe(false);
    });

    it('ignores units from other surahs', () => {
        const units = [unit('2:1:1'), unit('1:1:1'), unit('1:1:2'), unit('1:1:3')];
        const cov = computeChapterCoverage(units, 1, refCounts);
        // Only chapter-1 verse 1 counts; verses 2 & 3 are fully missing.
        expect(cov.status.get(2)).toBe('full');
        expect(cov.status.get(3)).toBe('full');
        expect(cov.status.has(1)).toBe(false);
    });

    it('is fail-open when the reference is unavailable', () => {
        const cov = computeChapterCoverage([unit('1:1:1')], 1, undefined);
        expect(cov.numVerses).toBe(0);
        expect(cov.status.size).toBe(0);
    });

    it('treats a present verse with an unknown reference count as complete', () => {
        // refCounts has no entry for verse 3's count via a chapter whose map omits it.
        const partialRef = new Map<number, number>([[1, 3], [2, 5], [3, 0]]);
        const units = [
            unit('1:1:1'), unit('1:1:2'), unit('1:1:3'),
            unit('1:2:1'), unit('1:2:2'), unit('1:2:3'), unit('1:2:4'), unit('1:2:5'),
            unit('1:3:1'),
        ];
        const cov = computeChapterCoverage(units, 1, partialRef);
        // verse 3 ref count is 0/unknown → not flagged even though only word 1 recited.
        expect(cov.status.has(3)).toBe(false);
    });
});
