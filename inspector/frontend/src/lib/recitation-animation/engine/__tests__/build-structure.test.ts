import { describe, expect, it } from 'vitest';

import { type AnimSourceWord, buildAnimStructure } from '../build-structure';

const SALA = 'ۖ'; // surfaced permissible-stop mark
const LA = 'ۙ'; // لا — "do not stop", never surfaced

function word(display: string, letters: AnimSourceWord['letters'] = []): AnimSourceWord {
    return { text: display, display_text: display, start: 0, end: 1, letters };
}

describe('buildAnimStructure waqf split', () => {
    it('pulls a surfaced stop mark out of the reveal text into `waqf`', () => {
        const [w] = buildAnimStructure([word(`فمن${SALA}`)]);
        expect(w!.clean).toBe('فمن');
        expect(w!.waqf).toBe(SALA);
        // The stripped mark must not survive as a char group (never revealed).
        expect(w!.chars.some((c) => c.text.includes(SALA))).toBe(false);
    });

    it('keeps the لا (no-stop) mark inside the word and leaves `waqf` null', () => {
        const [w] = buildAnimStructure([word(`فمن${LA}`)]);
        expect(w!.clean).toBe(`فمن${LA}`);
        expect(w!.waqf).toBeNull();
    });

    it('leaves a plain word untouched', () => {
        const [w] = buildAnimStructure([word('بِسْمِ')]);
        expect(w!.clean).toBe('بِسْمِ');
        expect(w!.waqf).toBeNull();
    });
});
