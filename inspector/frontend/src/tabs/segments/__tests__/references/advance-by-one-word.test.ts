/**
 * _advanceRefByOneWord — used by the split-chain handoff to compute the
 * second half's start point from the just-committed first half's end.
 */

import { describe, expect,it } from 'vitest';

import { _advanceRefByOneWord } from '../../utils/data/references';

// surah 1: verse 1 has 4 words, verse 2 has 5 words, no verse 3 (surah end).
// surah 2: verse 1 has 3 words.
const vwc = { '1:1': 4, '1:2': 5, '2:1': 3 };

describe('_advanceRefByOneWord', () => {
    it('mid-verse: returns word + 1 in the same verse', () => {
        expect(_advanceRefByOneWord({ surah: 1, ayah: 1, word: 2 }, vwc))
            .toEqual({ surah: 1, ayah: 1, word: 3 });
    });

    it('last word of verse: rolls over to {ayah+1, word: 1}', () => {
        expect(_advanceRefByOneWord({ surah: 1, ayah: 1, word: 4 }, vwc))
            .toEqual({ surah: 1, ayah: 2, word: 1 });
    });

    it('last word of last verse of surah: returns null (no cross-surah rollover)', () => {
        expect(_advanceRefByOneWord({ surah: 1, ayah: 2, word: 5 }, vwc)).toBeNull();
    });

    it('vwc unavailable: returns null', () => {
        expect(_advanceRefByOneWord({ surah: 1, ayah: 1, word: 2 }, undefined)).toBeNull();
    });

    it('verse not in vwc: returns null (defensive)', () => {
        expect(_advanceRefByOneWord({ surah: 99, ayah: 1, word: 1 }, vwc)).toBeNull();
    });
});
