import { describe, expect, it } from 'vitest';

import type { TsWord } from '../../../../lib/types/domain';
import { stopRefsFromGaps } from '../stops';

function word(start: number, end: number, location: string): TsWord {
    return {
        location,
        text: '',
        display_text: '',
        start,
        end,
        phoneme_indices: [],
        letters: [],
    };
}

describe('stopRefsFromGaps', () => {
    it('returns no stops for a gapless verse (continuous breath group)', () => {
        // MFA word.end touches the next word.start across the verse —
        // the signature of a single uninterrupted recitation.
        const words = [
            word(0, 1, '2:8:1'),
            word(1, 2, '2:8:2'),
            word(2, 3, '2:8:3'),
        ];
        expect(stopRefsFromGaps(words)).toEqual([]);
    });

    it('emits the BEFORE word of every gap', () => {
        // A pause sits between word 2 and word 3 (b.start > a.end) —
        // emit "2:8:2" so the phonemizer treats `man` as a waqf and
        // doesn't merge the noon idgham cross-word into `yaqūlu`.
        const words = [
            word(0, 1, '2:8:1'),
            word(1, 2, '2:8:2'),
            word(2.5, 3.5, '2:8:3'),
        ];
        expect(stopRefsFromGaps(words)).toEqual(['2:8:2']);
    });

    it('emits multiple stops in word order', () => {
        const words = [
            word(0, 1, '2:8:1'),
            word(1.4, 2, '2:8:2'),
            word(2, 3, '2:8:3'),
            word(3.2, 4, '2:8:4'),
        ];
        expect(stopRefsFromGaps(words)).toEqual(['2:8:1', '2:8:3']);
    });

    it('handles 0 or 1 word verses without throwing', () => {
        expect(stopRefsFromGaps([])).toEqual([]);
        expect(stopRefsFromGaps([word(0, 1, '1:1:1')])).toEqual([]);
    });

    it('ignores zero-gap touches (b.start == a.end is NOT a pause)', () => {
        // Continuous transitions land at exact equality in ms-rounded MFA output.
        // Treating equality as a stop would suppress idgham across every word
        // boundary in a normal recitation.
        const words = [
            word(0, 1.0, '2:8:1'),
            word(1.0, 2.0, '2:8:2'),
        ];
        expect(stopRefsFromGaps(words)).toEqual([]);
    });
});
