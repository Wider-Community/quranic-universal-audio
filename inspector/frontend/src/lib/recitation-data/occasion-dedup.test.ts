import { describe, expect, it } from 'vitest';

import { canonicalClip, groupVerseOccasions, maxWordIndex } from './occasion-dedup';
import type { SegmentEntry } from '../types/api';

function seg(ref: string, s: number, e: number, widxs: number[]): SegmentEntry {
    const span = e - s;
    const n = widxs.length;
    const words = widxs.map((wi, i) => {
        const ws = s + Math.floor((span * i) / Math.max(n, 1));
        const we = s + Math.floor((span * (i + 1)) / Math.max(n, 1));
        return [wi, ws, we, [], []] as SegmentEntry['words'][number];
    });
    return { ref, t: [s, e], words };
}

function widxs(words: SegmentEntry['words']): number[] {
    return words.map((w) => w[0]);
}

describe('canonicalClip leading false-start trim', () => {
    it('drops a redundant prefix that restarts at word 1 and completes', () => {
        const occasion = [seg('1:1', 0, 1000, [1, 2, 3]), seg('1:1', 1000, 3000, [1, 2, 3, 4, 5])];
        const clip = canonicalClip(occasion, maxWordIndex(occasion));
        expect(widxs(clip.words)).toEqual([1, 2, 3, 4, 5]);
        expect(clip.startMs).toBe(1000); // clip starts at the restart
        expect(clip.endMs).toBe(3000);
    });

    it('keeps a mid-verse lookback (backward jump to a non-first word)', () => {
        // Completes at the first segment; trailing lookback trimmed, leading kept.
        const occasion = [seg('1:1', 0, 1500, [1, 2, 3, 4, 5]), seg('1:1', 1500, 3000, [3, 4, 5])];
        const clip = canonicalClip(occasion, maxWordIndex(occasion));
        expect(widxs(clip.words)).toEqual([1, 2, 3, 4, 5]);
        expect(clip.startMs).toBe(0);
    });
});

describe('groupVerseOccasions earliest canonical', () => {
    it('picks the earliest completing occasion when a verse is re-done', () => {
        const segments = [
            seg('1:1', 0, 1000, [1, 2, 3]),
            seg('1:2', 1000, 1500, [1, 2]),
            seg('1:1', 1500, 2500, [1, 2, 3]),
        ];
        const grouped = groupVerseOccasions(segments);
        const v11 = grouped.find((g) => g.ref === '1:1')!;
        expect(v11.canonical[0]!.t[0]).toBe(0); // earliest take
    });
});
