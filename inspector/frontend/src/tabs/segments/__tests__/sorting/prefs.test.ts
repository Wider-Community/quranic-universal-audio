/**
 * Validation-sort preference store — registry-default fallback, stale-kind
 * rejection, direction toggle, and localStorage persistence.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { LS_KEYS } from '../../../../lib/utils/constants';
import { resolveSort, selectSort, type SortPrefs, toggleDir, valSortPrefs } from '../../stores/validation-sort';

beforeEach(() => {
    valSortPrefs.set({});
    localStorage.clear();
    valSortPrefs.set({});
});

afterEach(() => {
    valSortPrefs.set({});
    localStorage.clear();
});

describe('resolveSort — defaults', () => {
    it('returns the registry default when no preference is stored', () => {
        expect(resolveSort({}, 'low_confidence')).toEqual({ kind: 'confidence', dir: 'asc' });
        expect(resolveSort({}, 'qalqala')).toEqual({ kind: 'quran_order', dir: 'asc' });
        expect(resolveSort({}, 'cross_verse')).toEqual({ kind: 'quran_order', dir: 'asc' });
    });

    it('returns null for an accordion that offers no sorts', () => {
        expect(resolveSort({}, 'missing_verses')).toBeNull();
        expect(resolveSort({}, '__flagged__')).toBeNull();
    });

    it('rejects a stored kind the category no longer offers', () => {
        // verse_count is not a qalqala option — fall back to its default.
        const prefs = { qalqala: { kind: 'verse_count' as const, dir: 'desc' as const } };
        expect(resolveSort(prefs, 'qalqala')).toEqual({ kind: 'quran_order', dir: 'asc' });
    });

    it('honours a valid stored preference', () => {
        const prefs = { cross_verse: { kind: 'verse_count' as const, dir: 'desc' as const } };
        expect(resolveSort(prefs, 'cross_verse')).toEqual({ kind: 'verse_count', dir: 'desc' });
    });
});

describe('selectSort / toggleDir', () => {
    it('selects a kind at its default direction', () => {
        selectSort('cross_verse', 'verse_count');
        expect(resolveSort(get(), 'cross_verse')).toEqual({ kind: 'verse_count', dir: 'asc' });
    });

    it('flips direction on the active kind', () => {
        toggleDir('qalqala');
        expect(resolveSort(get(), 'qalqala')).toEqual({ kind: 'quran_order', dir: 'desc' });
        toggleDir('qalqala');
        expect(resolveSort(get(), 'qalqala')).toEqual({ kind: 'quran_order', dir: 'asc' });
    });

    it('persists the choice to localStorage', () => {
        selectSort('missing_words', 'word_count');
        const raw = localStorage.getItem(LS_KEYS.SEG_VAL_SORTS);
        expect(raw).toBeTruthy();
        expect(JSON.parse(raw as string)).toMatchObject({ missing_words: { kind: 'word_count', dir: 'asc' } });
    });
});

// Snapshot the current store value (helper to keep the assertions terse).
function get(): SortPrefs {
    let v: SortPrefs = {};
    valSortPrefs.subscribe((s) => (v = s))();
    return v;
}
