import { describe, expect, it } from 'vitest';

import { chapterOccasions } from './occasions';
import type { SegmentEntry } from '../types/ts-client';

function seg(ref: string, s: number, e: number, widxs: number[] = [1]): SegmentEntry {
    return {
        ref,
        t: [s, e],
        words: widxs.map((wi) => [wi, s, e, [], []] as SegmentEntry['words'][number]),
    };
}

describe('chapterOccasions', () => {
    it('groups consecutive same-verse segments (false start + take) into one occasion', () => {
        const occ = chapterOccasions([
            seg('1:1', 0, 1000, [1, 2, 3]),
            seg('1:1', 1000, 3000, [1, 2, 3, 4, 5]),
        ]);
        expect(occ).toHaveLength(1);
        expect(occ[0]!.ref).toBe('1:1');
        expect(occ[0]!.segments).toHaveLength(2);
        expect(occ[0]!.firstStartMs).toBe(0);
    });

    it('splits a verse re-recited after a foreign verse into separate occasions', () => {
        const occ = chapterOccasions([
            seg('1:1', 0, 1000),
            seg('1:2', 1000, 1500),
            seg('1:1', 1500, 2500),
        ]);
        expect(occ.map((o) => o.ref)).toEqual(['1:1', '1:2', '1:1']);
        expect(occ[0]!.firstStartMs).toBe(0);
        expect(occ[2]!.firstStartMs).toBe(1500);
    });

    it('orders occasions by audio start, regardless of input order', () => {
        const occ = chapterOccasions([
            seg('1:3', 3000, 4000),
            seg('1:1', 0, 1000),
            seg('1:2', 1000, 2000),
        ]);
        expect(occ.map((o) => o.ref)).toEqual(['1:1', '1:2', '1:3']);
    });

    it('keeps every recited word — no dedup of a within-occasion repeat', () => {
        const occ = chapterOccasions([
            seg('1:1', 0, 1000, [1, 2]),
            seg('1:1', 1000, 2000, [1, 2]), // consecutive repeat — same occasion
        ]);
        expect(occ).toHaveLength(1);
        const widxs = occ[0]!.segments.flatMap((s) => s.words.map((w) => w[0]));
        expect(widxs).toEqual([1, 2, 1, 2]);
    });
});
