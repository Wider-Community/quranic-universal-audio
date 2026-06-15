/**
 * Sort abstraction — key extraction across the heterogeneous item shapes,
 * direction handling, and the secondary-tiebreaker resolution.
 */
import { describe, expect, it } from 'vitest';

import type { SegValAnyItem } from '../../../../lib/types/generated/schemas';
import { defaultOption, keyFor, type SortOption, sortItems } from '../../domain/sorting';

// Loose item factory — items carry no on-wire discriminator.
const item = (o: Record<string, unknown>): SegValAnyItem => o as unknown as SegValAnyItem;

describe('keyFor — quran_order', () => {
    it('uses (chapter, seg_index) for per-segment items', () => {
        expect(keyFor('quran_order', item({ chapter: 2, seg_index: 5 }))).toEqual([2, 5]);
    });

    it('falls back to (surah, ayah) from verse_key for verse-scoped items', () => {
        expect(keyFor('quran_order', item({ chapter: 2, verse_key: '2:10' }))).toEqual([2, 10]);
    });

    it('parses the ref start when neither seg_index nor verse_key is present', () => {
        expect(keyFor('quran_order', item({ ref: '2:10:5-2:11:3' }))).toEqual([2, 10, 5]);
    });

    it('orders failed items (no ref) by neighbour position', () => {
        expect(keyFor('quran_order', item({ chapter: 3, seg_index: 1, time: '0-1' }))).toEqual([3, 1]);
        expect(keyFor('quran_order', item({ chapter: 3, seg_index: 8, time: '2-3' }))).toEqual([3, 8]);
    });
});

describe('keyFor — count kinds', () => {
    it('confidence reads the score', () => {
        expect(keyFor('confidence', item({ confidence: 0.42 }))).toEqual([0.42]);
    });

    it('word_count reads missing_words length', () => {
        expect(keyFor('word_count', item({ missing_words: [1, 2, 3] }))).toEqual([3]);
        expect(keyFor('word_count', item({}))).toEqual([0]);
    });

    it('verse_count derives the span from a cross-verse ref', () => {
        expect(keyFor('verse_count', item({ ref: '2:10:5-2:12:1' }))).toEqual([3]);
        expect(keyFor('verse_count', item({ ref: '2:10:5-2:10:9' }))).toEqual([1]);
    });

    it('rep_split_count reads refs.length from the auto-split map by uid', () => {
        const ctx = { autoSplitMap: { 'uid-1': { refs: ['a', 'b', 'c'] } } };
        expect(keyFor('rep_split_count', item({ segment_uid: 'uid-1' }), ctx)).toEqual([3]);
        expect(keyFor('rep_split_count', item({ segment_uid: 'absent' }), ctx)).toEqual([1]);
        expect(keyFor('rep_split_count', item({ segment_uid: 'uid-1' }))).toEqual([1]);
    });
});

describe('sortItems', () => {
    const opts: SortOption[] = [{ kind: 'quran_order', default: true }, { kind: 'word_count' }];

    it('sorts ascending and descending by the active kind', () => {
        const items = [
            item({ chapter: 1, seg_index: 3 }),
            item({ chapter: 1, seg_index: 1 }),
            item({ chapter: 1, seg_index: 2 }),
        ];
        const asc = sortItems(items, 'quran_order', 'asc', opts).map((i) => (i as { seg_index: number }).seg_index);
        const desc = sortItems(items, 'quran_order', 'desc', opts).map((i) => (i as { seg_index: number }).seg_index);
        expect(asc).toEqual([1, 2, 3]);
        expect(desc).toEqual([3, 2, 1]);
    });

    it('does not mutate the input array', () => {
        const items = [item({ chapter: 1, seg_index: 2 }), item({ chapter: 1, seg_index: 1 })];
        const snapshot = items.slice();
        sortItems(items, 'quran_order', 'asc', opts);
        expect(items).toEqual(snapshot);
    });

    it('breaks ties on the active key with the other option (ascending)', () => {
        // Active = word_count asc; equal counts fall back to quran_order asc.
        const items = [
            item({ chapter: 1, seg_index: 9, verse_key: '1:9', missing_words: [1, 2] }),
            item({ chapter: 1, seg_index: 2, verse_key: '1:2', missing_words: [1, 2] }),
            item({ chapter: 1, seg_index: 5, verse_key: '1:5', missing_words: [1] }),
        ];
        const ordered = sortItems(items, 'word_count', 'asc', opts).map(
            (i) => (i as { seg_index: number }).seg_index,
        );
        // count 1 first (seg 5), then the two count-2 items by quran order (2, 9).
        expect(ordered).toEqual([5, 2, 9]);
    });
});

describe('defaultOption', () => {
    it('returns the option flagged default', () => {
        expect(defaultOption([{ kind: 'quran_order' }, { kind: 'confidence', default: true }])?.kind).toBe('confidence');
    });
    it('falls back to the first option when none is flagged', () => {
        expect(defaultOption([{ kind: 'word_count' }, { kind: 'quran_order' }])?.kind).toBe('word_count');
    });
    it('returns null for an empty/absent list', () => {
        expect(defaultOption([])).toBeNull();
        expect(defaultOption(undefined)).toBeNull();
    });
});
