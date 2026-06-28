import { describe, expect, it } from 'vitest';

import type { SegmentEntry, TsShardResponse } from '../../types/ts-client';
import { assembleOccasion, shardOccasions, type TsReciterAudio } from '../ts-source';

/**
 * Regression: re-stamped shards consolidate per-letter facts into cells +
 * phonemes and leave the legacy `letters` slot empty (the analysis letter row
 * renders straight from cells, but the teleprompter / filmstrip drive their
 * reveal off `Letter[]`). When the slot is empty, the assembler must reconstruct
 * `letters` from the cell rows so per-letter animation keeps working — otherwise
 * every char collapses to the word span and char mode looks like word mode.
 */

const RA: TsReciterAudio = { audio_category: 'by_surah' };
const TXT: Record<string, { text?: string }> = {};

function shardOf(words: SegmentEntry['words']): TsShardResponse {
    return {
        _meta: {} as TsShardResponse['_meta'],
        segments: [{ ref: '2:1', t: [0, 400], words }],
    };
}

describe('assembleOccasion — letters reconstructed from cells when the slot is empty', () => {
    it('groups cells by sourceLetterIndex into timed letters; a phone-less group is silent', () => {
        // word "بَنْاْ": ب(+fatha) ن(+sukoon, sounded) ا(silent carrier, no phone).
        const word: SegmentEntry['words'][number] = [
            1, 0, 300,
            [], // empty letters slot — the re-stamped shape
            [['b', 0, 100], ['a', 100, 200], ['n', 200, 300]], // 3 indexable phones
            [
                ['ب', 'base', 'present', [0], 0],
                ['َ', 'haraka', 'present', [1], 0],
                ['ن', 'base', 'present', [2], 1],
                ['ْ', 'haraka', 'present', [], 1],
                ['ا', 'base', 'silent', [], 2],
            ],
        ];
        const occ = shardOccasions(shardOf([word]))[0]!;
        const d = assembleOccasion('r', occ, TXT, TXT, RA, '');
        const letters = d.words[0]!.letters;

        expect(letters.map((l) => l.char)).toEqual(['ب', 'ن', 'ا']);
        // ب spans its base+haraka phones [0,0.2]; ن spans its sounded phone [0.2,0.3].
        expect(letters[0]).toMatchObject({ char: 'ب', start: 0, end: 0.2, silent: false });
        expect(letters[1]).toMatchObject({ char: 'ن', start: 0.2, end: 0.3, silent: false });
        // The silent carrier has no phoneme → null timing + silent flag.
        expect(letters[2]).toMatchObject({ char: 'ا', start: null, end: null, silent: true });
    });

    it('keeps the shard-provided letters verbatim when the slot is populated', () => {
        const word: SegmentEntry['words'][number] = [
            1, 0, 200,
            [['ق', 0, 120, false], ['ل', 120, 200, false]], // real slot-3 letters
            [['q', 0, 120], ['l', 120, 200]],
            [
                ['ق', 'base', 'present', [0], 0],
                ['ل', 'base', 'present', [1], 1],
            ],
        ];
        const occ = shardOccasions(shardOf([word]))[0]!;
        const d = assembleOccasion('r', occ, TXT, TXT, RA, '');
        const letters = d.words[0]!.letters;

        expect(letters.map((l) => l.char)).toEqual(['ق', 'ل']);
        expect(letters[0]).toMatchObject({ char: 'ق', start: 0, end: 0.12 });
        expect(letters[1]).toMatchObject({ char: 'ل', start: 0.12, end: 0.2 });
    });
});
