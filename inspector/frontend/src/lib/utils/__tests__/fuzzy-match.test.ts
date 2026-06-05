import { describe, expect, it } from 'vitest';

import { match, normalizeArabic } from '../fuzzy-match';

describe('normalizeArabic', () => {
    // Each assertion now pins the EXPECTED canonical form rather than just
    // comparing two normalised values to each other. The latter pattern
    // passes when both inputs reduce to the empty string — masking a bug
    // where the diacritic regex eats base letters too. A negative guard
    // (different unicode preserved) blocks the all-collapse-to-empty mode
    // from recurring silently.
    it('strips tashkeel diacritics', () => {
        expect(normalizeArabic('مَكْتَبَة')).toBe('مكتبه');
    });

    it('collapses alif variants', () => {
        expect(normalizeArabic('أحمد')).toBe('احمد');
        expect(normalizeArabic('إبراهيم')).toBe('ابراهيم');
        expect(normalizeArabic('آدم')).toBe('ادم');
    });

    it('maps taa marbuta to haa', () => {
        expect(normalizeArabic('الفاتحة')).toBe('الفاتحه');
    });

    it('maps alif maksura to yaa', () => {
        expect(normalizeArabic('موسى')).toBe('موسي');
    });

    it('lowercases Latin', () => {
        expect(normalizeArabic('Husary')).toBe('husary');
    });

    it('passes empty input through', () => {
        expect(normalizeArabic('')).toBe('');
    });

    it('does not collapse distinct base letters to a single value', () => {
        // Negative guard: a regex that ate base Arabic letters would make
        // both of these collapse to '' and the previous comparison-only
        // tests would all pass.
        expect(normalizeArabic('مكتب')).not.toBe(normalizeArabic('مكتبه'));
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
