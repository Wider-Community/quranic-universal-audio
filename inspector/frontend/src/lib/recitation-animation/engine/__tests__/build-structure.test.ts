import { describe, expect, it } from 'vitest';

import { type AnimSourceWord, buildAnimStructure } from '../build-structure';

const SALA = 'ۖ'; // surfaced permissible-stop mark
const LA = 'ۙ'; // لا — "do not stop", never surfaced
const RUB = '۞'; // ۞ rub-el-hizb section marker (leading, non-recited)
const SAJDAH = '۩'; // ۩ place-of-sajdah mark (trailing, non-recited)

function word(display: string, letters: AnimSourceWord['letters'] = []): AnimSourceWord {
    return { text: display, display_text: display, start: 0, end: 1, letters };
}

describe('buildAnimStructure decorators', () => {
    it('pulls a surfaced stop mark into a trailing waqf decorator, never a char cell', () => {
        const [w] = buildAnimStructure([word(`فمن${SALA}`)]);
        expect(w!.clean).toBe('فمن');
        expect(w!.trailing.map((d) => d.glyph)).toEqual([SALA]);
        expect(w!.trailing[0]!.role).toBe('waqf');
        // The stripped mark must not survive as a char group (never revealed).
        expect(w!.chars.some((c) => c.text.includes(SALA))).toBe(false);
    });

    it('keeps the no-stop (laa) mark inside the word with no decorator', () => {
        const [w] = buildAnimStructure([word(`فمن${LA}`)]);
        expect(w!.clean).toBe(`فمن${LA}`);
        expect(w!.leading).toEqual([]);
        expect(w!.trailing).toEqual([]);
    });

    it('renders rub-el-hizb as a leading decorator, never a char cell', () => {
        const [w] = buildAnimStructure([word(`${RUB}فمن`)]);
        expect(w!.clean).toBe('فمن');
        expect(w!.leading.map((d) => d.glyph)).toEqual([RUB]);
        expect(w!.leading[0]!.role).toBe('rub');
        expect(w!.chars.some((c) => c.text.includes(RUB))).toBe(false);
    });

    it('renders the sajdah mark as a trailing decorator, never a char cell', () => {
        const [w] = buildAnimStructure([word(`فمن${SAJDAH}`)]);
        expect(w!.clean).toBe('فمن');
        expect(w!.trailing.map((d) => d.glyph)).toEqual([SAJDAH]);
        expect(w!.trailing[0]!.role).toBe('sajdah');
        expect(w!.chars.some((c) => c.text.includes(SAJDAH))).toBe(false);
    });

    it('leaves a plain word with no decorators', () => {
        const [w] = buildAnimStructure([word('بِسْمِ')]);
        expect(w!.clean).toBe('بِسْمِ');
        expect(w!.leading).toEqual([]);
        expect(w!.trailing).toEqual([]);
    });
});

describe('buildAnimStructure letter timing', () => {
    // Mini-yaa (U+06E7) carries its own MFA timestamp; it gets its own cell,
    // stamped with its own interval, so it highlights independently of its base.
    it('gives the mini-yaa its own independently-timed cell', () => {
        const letters = [
            { char: 'ح', start: 0, end: 1 }, // haa
            { char: 'ۧ', start: 1, end: 2 }, // mini-yaa
            { char: 'ي', start: 2, end: 3 }, // yaa
        ];
        const display = 'حۧي';
        const [w] = buildAnimStructure([
            { text: display, display_text: display, start: 0, end: 3, letters },
        ]);
        const yaa = w!.chars.find((c) => c.text.includes('ۧ'));
        expect(yaa).toBeDefined();
        expect(yaa!.start).toBe(1);
        expect(yaa!.end).toBe(2);
    });

    // Regression: a display cell with no matching MFA letter must NOT keep
    // whole-word timing (which would light it for the whole word, in lockstep
    // with the real first letter). It inherits a neighbour's interval instead.
    it('never leaves an unmatched cell on whole-word timing', () => {
        const letters = [
            { char: 'س', start: 0, end: 1 }, // seen
            { char: 'و', start: 2, end: 3 }, // waw
        ];
        // seen + small hamza (U+0654) + waw — the hamza has no MFA letter.
        const display = 'سٔو';
        const [w] = buildAnimStructure([
            { text: display, display_text: display, start: 0, end: 3, letters },
        ]);
        for (const c of w!.chars) {
            expect(c.start === 0 && c.end === 3).toBe(false);
        }
    });
});
