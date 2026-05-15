import { describe, expect, it } from 'vitest';

import { match, normalizeArabic } from '../fuzzy-match';

describe('normalizeArabic', () => {
    it('strips tashkeel diacritics', () => {
        expect(normalizeArabic('مَكْتَبَة')).toBe(normalizeArabic('مكتبه'));
    });

    it('collapses alif variants', () => {
        expect(normalizeArabic('أحمد')).toBe(normalizeArabic('احمد'));
        expect(normalizeArabic('إبراهيم')).toBe(normalizeArabic('ابراهيم'));
        expect(normalizeArabic('آدم')).toBe(normalizeArabic('ادم'));
    });

    it('maps taa marbuta to haa', () => {
        expect(normalizeArabic('الفاتحة')).toBe(normalizeArabic('الفاتحه'));
    });

    it('maps alif maksura to yaa', () => {
        expect(normalizeArabic('موسى')).toBe(normalizeArabic('موسي'));
    });

    it('lowercases Latin', () => {
        expect(normalizeArabic('Husary')).toBe(normalizeArabic('husary'));
    });

    it('passes empty input through', () => {
        expect(normalizeArabic('')).toBe('');
    });
});

describe('match', () => {
    it('returns true for empty needle (no query)', () => {
        expect(match('anything', '')).toBe(true);
    });

    it('matches Arabic substring via normalization', () => {
        expect(match('سُورَةُ الْفَاتِحَة', 'فاتحه')).toBe(true);
    });

    it('matches Latin substring case-insensitively', () => {
        expect(match('Mishary Rashid Al-Afasy', 'rashid')).toBe(true);
    });

    it('returns false when the substring is absent', () => {
        expect(match('Husary', 'afasy')).toBe(false);
    });
});
