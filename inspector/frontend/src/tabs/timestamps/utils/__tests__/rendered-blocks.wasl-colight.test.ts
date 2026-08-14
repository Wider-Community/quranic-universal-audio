/**
 * Cross-verse waṣl co-light: a verse-final tanwīn that idgham-merges into the next
 * verse's head must highlight THROUGH the ghunnah (the merger phone), like every
 * intra-verse merger. The source tanwīn (verse A) and the receiving nasalised head
 * (verse B) sit in different segments, so they were renumbered into separate
 * share-groups and stopped co-lighting; `buildRendered` re-links them.
 */
import { describe, expect, it } from 'vitest';

import type { Letter, PhonemeInterval, TsCell, TsWord } from '../../../../lib/types/ts-client';
import { buildRendered } from '../rendered-blocks';

function ph(phone: string, start: number, end: number): PhonemeInterval {
    return { phone, start, end };
}
function cell(over: Partial<TsCell>): TsCell {
    return { chars: '', role: 'base', status: 'present', phonemeIndices: [], sourceLetterIndex: 0, rules: [], shareGroup: null, ...over };
}
function word(location: string, idxs: number[], letters: string, cells: TsCell[]): TsWord {
    const ls: Letter[] = [...letters].map((c) => ({ char: c, start: null, end: null }));
    return { location, text: letters, display_text: letters, start: 0, end: 0, phoneme_indices: idxs, letters: ls, cells };
}

// Flat intervals: 0 ب, 1 ٍ-leftover-vowel, 2 w̃ (the merger the next verse receives), 3 ج.
const intervals: PhonemeInterval[] = [ph('b', 1, 1.6), ph('i', 1.6, 2), ph('w̃', 2, 2.4), ph('dʒ', 2.4, 3)];

function shape(secondLocation: string): TsWord[] {
    return [
        word('1:1:2', [0, 1], 'بٍ', [
            cell({ chars: 'ب', phonemeIndices: [0] }),
            cell({ chars: 'ٍ', role: 'tanween', phonemeIndices: [1], sourceLetterIndex: 1, rules: ['idgham_bi_ghunnah'], shareGroup: 0 }),
        ]),
        word(secondLocation, [2, 3], 'وج', [
            cell({ chars: 'و', phonemeIndices: [2] }), // receives the w̃ merger head
            cell({ chars: 'ج', phonemeIndices: [3], sourceLetterIndex: 1 }),
        ]),
    ];
}

/** The tanwīn diacritic of the source word `1:1:2` (its only small/diacritic cell). */
function tanwinCell(words: TsWord[]) {
    for (const b of buildRendered(words, intervals)) {
        if (b.word.location !== '1:1:2') continue;
        for (const g of b.groups) {
            for (const s of g.small) return s;
        }
    }
    return null;
}

describe('buildRendered — cross-verse waṣl co-light', () => {
    it('extends the tanwīn highlight through the next verse ghunnah (re-linked share group)', () => {
        const t = tanwinCell(shape('1:2:1')); // verse B → cross-verse junction
        expect(t).not.toBeNull();
        // union with the receiver's w̃ [2, 2.4] — NOT the tanwīn's own vowel end (2.0).
        expect(t!.cellEnd).toBe(2.4);
    });

    it('does not extend across a same-verse boundary (no spurious union)', () => {
        const t = tanwinCell(shape('1:1:3')); // same verse → not a cross-verse junction
        expect(t!.cellEnd).toBe(2); // tanwīn keeps its own vowel span
    });
});
