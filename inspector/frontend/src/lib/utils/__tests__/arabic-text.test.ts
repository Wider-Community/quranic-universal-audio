import { describe, expect, it } from 'vitest';

import {
    charsMatch,
    firstBase,
    isCombiningMark,
    splitIntoCharGroups,
    stripTashkeel,
    toArabicNumeral,
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

    it('recognises the small waw / yeh that ride a base (U+06E5–U+06E6)', () => {
        // Lm by Unicode category, but they stack on the preceding letter (e.g. the
        // small-waw long-madd marker), so the teleprompter treats them as riding.
        expect(isCombiningMark(0x06e5)).toBe(true);
        expect(isCombiningMark(0x06e6)).toBe(true);
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

    it('strips tatweel (U+0640) from the display char before comparing', () => {
        expect(charsMatch('ب', 'بـ')).toBe(true);
    });

    it('matches via mfaChar containing stripped display (reverse direction)', () => {
        // MFA letter is longer than display char and contains it — exercises
        // the otherwise-untested ``mfaChar.includes(stripped)`` branch.
        expect(charsMatch('بسم', 'ب')).toBe(true);
    });
});

describe('toArabicNumeral', () => {
    it('maps ASCII digits to Arabic-Indic numerals', () => {
        expect(toArabicNumeral(12)).toBe('١٢');
        expect(toArabicNumeral('2025')).toBe('٢٠٢٥');
    });

    it('leaves non-digit characters untouched — spaces are NOT digits', () => {
        // Regression: a char-by-char `+d` maps a space to 0 (`+' ' === 0`),
        // turning "أسلوب واحد" into "أسلوب٠واحد" (a stray ٠ dot). Only 0-9 convert.
        expect(toArabicNumeral('أسلوب واحد')).toBe('أسلوب واحد');
        expect(toArabicNumeral('3 مجموعات')).toBe('٣ مجموعات');
    });

    it('localizes digits in mixed strings while preserving units and separators', () => {
        expect(toArabicNumeral('192 kbps')).toBe('١٩٢ kbps');
        expect(toArabicNumeral('3h 45m')).toBe('٣h ٤٥m');
        expect(toArabicNumeral('47/114')).toBe('٤٧/١١٤');
        // The ASCII '.' is not a digit, so it rides through unchanged.
        expect(toArabicNumeral('1.5×')).toBe('١.٥×');
    });
});

describe('splitIntoCharGroups', () => {
    it('groups base char + trailing combining marks', () => {
        // "بِسْمِ" → 3 groups: "بِ", "سْ", "مِ"
        const groups = splitIntoCharGroups('بِسْمِ');
        expect(groups).toHaveLength(3);
        expect(groups[0]).toBe('بِ');
    });

    it('U+0654 (hamza-above) rides its base as one cluster', () => {
        // A combining mark cannot be a separate run without detaching, so it
        // stays on its base — base + hamza = one group.
        const groups = splitIntoCharGroups('بٔ');
        expect(groups).toHaveLength(1);
    });

    it('U+0670 (dagger alef) starts its own group — it times/renders independently', () => {
        const groups = splitIntoCharGroups('بٰ');
        expect(groups).toHaveLength(2);
    });

    it('U+06E7 (mini-yaa) rides its base as one cluster', () => {
        const groups = splitIntoCharGroups('بۧ');
        expect(groups).toHaveLength(1);
    });

    it('U+2060 (word joiner) absorbs into the current group', () => {
        // base + U+2060 collapses into a single group.
        const groups = splitIntoCharGroups('ب⁠');
        expect(groups).toHaveLength(1);
    });
});
