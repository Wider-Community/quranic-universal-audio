import { describe, it, expect } from 'vitest';

import {
    charsMatch,
    firstBase,
    isCombiningMark,
    splitIntoCharGroups,
    stripTashkeel,
} from '../arabic-text';

describe('stripTashkeel', () => {
    it('removes tashkeel diacritics while preserving base letters', () => {
        // "بِسْمِ" (bismi) with tashkeel → "بسم" without
        expect(stripTashkeel('بِسْمِ')).toBe('بسم');
    });

    it('leaves text without tashkeel untouched', () => {
        expect(stripTashkeel('بسم')).toBe('بسم');
    });

    it('returns an empty string when given an empty string', () => {
        expect(stripTashkeel('')).toBe('');
    });
});

describe('isCombiningMark', () => {
    it('recognises Arabic tashkeel codepoints', () => {
        // Fatha (\u064E)
        expect(isCombiningMark(0x064e)).toBe(true);
        // Superscript alef (\u0670)
        expect(isCombiningMark(0x0670)).toBe(true);
    });

    it('rejects base Arabic letters', () => {
        // ب (bāʾ)
        expect(isCombiningMark(0x0628)).toBe(false);
    });
});

describe('firstBase', () => {
    it('returns the base letter, stripping any combining marks', () => {
        // "بِ" = ب + kasra → base is ب
        expect(firstBase('بِ')).toBe('ب');
    });
});

describe('charsMatch', () => {
    it('matches identical characters', () => {
        expect(charsMatch('ب', 'ب')).toBe(true);
    });

    it('treats alef-maksura and yaa as equivalent', () => {
        expect(charsMatch('\u064A', '\u0649')).toBe(true);
    });

    it('rejects unrelated characters', () => {
        expect(charsMatch('ب', 'م')).toBe(false);
    });
});

describe('splitIntoCharGroups', () => {
    it('groups base char + trailing combining marks', () => {
        // "بِسْمِ" → 3 groups: "بِ", "سْ", "مِ"
        const groups = splitIntoCharGroups('بِسْمِ');
        expect(groups).toHaveLength(3);
        expect(groups[0]).toBe('بِ');
    });
});
