import { describe, expect, it } from 'vitest';

import { type AnimSourceWord, buildAnimStructure } from '../build-structure';

const SALA = 'ۖ'; // surfaced permissible-stop mark
const LA = 'ۙ'; // لا — "do not stop", never surfaced
const RUB = '۞'; // rub-el-hizb — non-recited, rendered in place (inert)
const SAJDAH = '۩'; // place-of-sajdah — non-recited, rendered in place (inert)

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

    it('keeps rub-el-hizb in the reveal text as an inert cell, not a decorator', () => {
        const [w] = buildAnimStructure([word(`${RUB}فمن`)]);
        expect(w!.clean).toBe(`${RUB}فمن`);
        expect(w!.leading).toEqual([]);
        expect(w!.trailing).toEqual([]);
        const cell = w!.chars.find((c) => c.text.includes(RUB));
        expect(cell?.inert).toBe(true);
    });

    it('keeps the sajdah mark in the reveal text as an inert cell, not a decorator', () => {
        const [w] = buildAnimStructure([word(`فمن${SAJDAH}`)]);
        expect(w!.clean).toBe(`فمن${SAJDAH}`);
        expect(w!.leading).toEqual([]);
        expect(w!.trailing).toEqual([]);
        const cell = w!.chars.find((c) => c.text.includes(SAJDAH));
        expect(cell?.inert).toBe(true);
    });

    it('leaves a plain word with no decorators', () => {
        const [w] = buildAnimStructure([word('بِسْمِ')]);
        expect(w!.clean).toBe('بِسْمِ');
        expect(w!.leading).toEqual([]);
        expect(w!.trailing).toEqual([]);
    });
});

describe('buildAnimStructure letter timing', () => {
    // A combining mark can't be a separate highlight span without detaching, so
    // the mini-yaa (U+06E7) rides its base letter's cluster — its MFA timing is
    // folded into the base cell, which stays lit through the mark.
    it('folds the mini-yaa timing into its base cluster, no separate cell', () => {
        const letters = [
            { char: 'ح', start: 0, end: 1 }, // haa
            { char: 'ۧ', start: 1, end: 2 }, // mini-yaa, rides the haa
            { char: 'ي', start: 2, end: 3 }, // yaa
        ];
        const display = 'حۧي';
        const [w] = buildAnimStructure([
            { text: display, display_text: display, start: 0, end: 3, letters },
        ]);
        const haa = w!.chars.find((c) => c.text.startsWith('ح'));
        expect(haa).toBeDefined();
        expect(haa!.text).toContain('ۧ'); // mini-yaa is part of the haa cluster
        expect(haa!.start).toBe(0);
        expect(haa!.end).toBe(2); // extended to cover the mini-yaa's timing
        expect(w!.chars.filter((c) => c.text === 'ۧ')).toEqual([]); // no standalone cell
    });

    // Regression: an inert symbol cell (no MFA letter) must NOT keep whole-word
    // timing (which would light it for the whole word). It inherits a neighbour's
    // interval instead.
    it('gives an inert symbol cell neighbour timing, never whole-word timing', () => {
        const letters = [
            { char: 'ف', start: 0, end: 1 },
            { char: 'م', start: 1, end: 2 },
        ];
        const display = `فم${SAJDAH}`; // trailing sajdah has no MFA letter
        const [w] = buildAnimStructure([
            { text: display, display_text: display, start: 0, end: 5, letters },
        ]);
        const saj = w!.chars.find((c) => c.text.includes(SAJDAH));
        expect(saj?.inert).toBe(true);
        expect(saj!.start === 0 && saj!.end === 5).toBe(false);
    });
});
