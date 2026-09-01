import { get } from 'svelte/store';
import { afterEach, describe, expect, it } from 'vitest';

import type { SegValidateResponse } from '../../../../lib/types/generated/schemas';
import { missingWordsSegKeys, segValidation } from '../../stores/validation';
import { deriveRowChips, segKey } from '../../utils/samples/chips';

const NONE = new Set<string>();

describe('deriveRowChips', () => {
    it('flags low confidence and failed matches', () => {
        expect(deriveRowChips({ index: 0, matched_ref: '1:1:1-1:1:2', confidence: 0.3 }, NONE, 1)).toEqual(['low_conf']);
        expect(deriveRowChips({ index: 0, matched_ref: '', confidence: 0.9 }, NONE, 1)).toEqual(['low_conf']);
        expect(deriveRowChips({ index: 0, matched_ref: '1:1:1-1:1:2', confidence: 0.95 }, NONE, 1)).toEqual([]);
    });

    it('flags repetitions off wrap_word_ranges only', () => {
        const seg = { index: 2, matched_ref: '1:1:1-1:1:4', confidence: 0.9, wrap_word_ranges: [['1:1:1', '1:1:2']] };
        expect(deriveRowChips(seg, NONE, 1)).toEqual(['repetition']);
    });

    it('flags missing words by chapter:index key', () => {
        const keys = new Set([segKey(2, 5)]);
        const seg = { index: 5, matched_ref: '2:1:1-2:1:3', confidence: 0.9 };
        expect(deriveRowChips(seg, keys, 2)).toEqual(['missing_words']);
        expect(deriveRowChips(seg, keys, 3)).toEqual([]);
    });
});

describe('missingWordsSegKeys', () => {
    afterEach(() => segValidation.set(null));

    it('collects every seg index of every missing_words item', () => {
        segValidation.set({
            missing_words: [
                { verse_key: '2:1', chapter: 2, segment_uid: null, msg: '', seg_indices: [1, 2] },
                { verse_key: '3:4', chapter: 3, segment_uid: null, msg: '', seg_indices: [7] },
            ],
        } as unknown as SegValidateResponse);
        expect([...get(missingWordsSegKeys)].sort()).toEqual(['2:1', '2:2', '3:7']);
    });

    it('is empty with no validation loaded', () => {
        expect(get(missingWordsSegKeys).size).toBe(0);
    });
});
