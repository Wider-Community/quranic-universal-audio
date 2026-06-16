import { describe, expect, it } from 'vitest';

import { hasWaqf, splitWaqf } from '../waqf';

const SALA = 'ۖ'; // ۖ — permissible stop
const QILA = 'ۗ'; // ۗ
const MEEM = 'ۘ'; // ۘ — must stop
const LA = 'ۙ'; // ۙ — do NOT stop (excluded)
const JEEM = 'ۚ'; // ۚ
const THREE = 'ۛ'; // ۛ — muanaqah
const SEEN = 'ۜ'; // ۜ — saktah

describe('hasWaqf', () => {
    it('detects each surfaced stop mark', () => {
        for (const m of [SALA, QILA, MEEM, JEEM, THREE, SEEN]) {
            expect(hasWaqf(`فمن${m}`)).toBe(true);
        }
    });

    it('ignores the لا (no-stop) mark', () => {
        expect(hasWaqf(`فمن${LA}`)).toBe(false);
    });

    it('is false for plain text', () => {
        expect(hasWaqf('بِسْمِ')).toBe(false);
    });
});

describe('splitWaqf', () => {
    it('strips the mark and returns it', () => {
        const { clean, mark } = splitWaqf(`فمن${SALA}`);
        expect(clean).toBe('فمن');
        expect(mark).toBe(SALA);
    });

    it('leaves text untouched when no surfaced mark is present', () => {
        const out = splitWaqf(`فمن${LA}`);
        // لا is not stripped (not a surfaced stop) — it stays in `clean`.
        expect(out.clean).toBe(`فمن${LA}`);
        expect(out.mark).toBeNull();
    });

    it('returns null mark for plain text', () => {
        expect(splitWaqf('بِسْمِ')).toEqual({ clean: 'بِسْمِ', mark: null });
    });

    it('captures the last mark when several appear', () => {
        const { clean, mark } = splitWaqf(`ا${SALA}ب${JEEM}`);
        expect(clean).toBe('اب');
        expect(mark).toBe(JEEM);
    });
});
