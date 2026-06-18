import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it } from 'vitest';

import { ZWSP } from '../../utils/arabic-text';
import { DEFAULT_RECITATION_CONFIG } from '../config';
import LineAnimation from '../LineAnimation.svelte';
import type { AnimUnit } from '../types';

const charConfig = {
    ...DEFAULT_RECITATION_CONFIG,
    granularity: 'char' as const,
    clearOnOverflow: false,
    clearOnAyahEnd: false,
    showAyahMarker: false,
};

function unit(
    location: string,
    text: string,
    start: number,
    end: number,
    letters: AnimUnit['letters'],
): AnimUnit {
    const [surahRaw, ayahRaw, wordRaw] = location.split(':');
    const surah = Number(surahRaw);
    const ayah = Number(ayahRaw);
    return {
        location,
        ayahKey: `${surah}:${ayah}`,
        surah,
        ayah,
        word: Number(wordRaw),
        text,
        start,
        end,
        intervals: [{ start, end }],
        letters,
    };
}

describe('LineAnimation char mode', () => {
    // happy-dom returns zero-sized rects from getBoundingClientRect, so
    // measureFits() treats every span as fitting on a single page. The test
    // relies on that to keep both words co-rendered; a real-browser layout
    // engine could pick a different page count for the same input. Do not
    // re-enable clearOnOverflow here without restoring the bounding rect
    // assumption explicitly (see LineAnimation.svelte:195).
    it('keeps cross-word co-timed letters visually active together', async () => {
        const units = [
            unit('1:1:1', 'ab', 0, 2, [
                { char: 'a', start: 0, end: 1 },
                { char: 'b', start: 1, end: 2 },
            ]),
            unit('1:1:2', 'cd', 1, 3, [
                { char: 'c', start: 1, end: 2 },
                { char: 'd', start: 2, end: 3 },
            ]),
        ];

        const { container } = render(LineAnimation, {
            units,
            config: charConfig,
            getTimeMs: () => 1500,
            playing: false,
        });
        await tick();

        const words = container.querySelectorAll<HTMLElement>('.ra-word');
        const chars = container.querySelectorAll<HTMLElement>('.ra-char');

        expect(chars[1]?.textContent).toBe('b');
        expect(chars[2]?.textContent).toBe('c');
        expect(chars[1]?.classList.contains('active')).toBe(true);
        expect(chars[2]?.classList.contains('active')).toBe(true);
        expect(words[0]?.classList.contains('active')).toBe(true);
        expect(words[1]?.classList.contains('active')).toBe(true);
    });

    const WAQF = 'ۖ'; // ARABIC SMALL HIGH SAD-LAM-ALEF-MEEM (a surfaced stop)
    // A 3-letter stop word (letters a[0,1] b[1,2] c[2,3], the mark riding the
    // last, c) plus a trailing word so the stop word can become reached.
    const stopUnit = () => unit('1:1:1', 'abc' + WAQF, 0, 3, [
        { char: 'a', start: 0, end: 1 },
        { char: 'b', start: 1, end: 2 },
        { char: 'c', start: 2, end: 3 },
    ]);
    const trailingUnit = () => unit('1:1:2', 'd', 3.2, 4.2, [{ char: 'd', start: 3.2, end: 4.2 }]);

    // The waqf sign is a standalone zero-advance glyph (`WORD JOINER + mark`),
    // decoupled from the letters — it never perturbs the per-letter reveal and is
    // never given the reveal highlight.
    it('renders the waqf mark as a standalone glyph that never takes the reveal', async () => {
        const { container } = render(LineAnimation, {
            units: [stopUnit()],
            config: charConfig,
            getTimeMs: () => 1500, // 'b' active
            playing: false,
        });
        await tick();

        // Per-letter reveal is unperturbed: the mark is stripped from `clean`, so
        // the chars are exactly 'a','b','c'.
        const chars = container.querySelectorAll<HTMLElement>('.ra-char');
        expect([...chars].map((c) => c.textContent)).toEqual(['a', 'b', 'c']);

        const marks = container.querySelectorAll<HTMLElement>('.ra-waqf-mark');
        expect(marks.length).toBe(1);
        expect(marks[0]?.textContent).toBe(ZWSP + WAQF);
        expect(marks[0]?.classList.contains('active')).toBe(false);
        expect(marks[0]?.classList.contains('waqf-active')).toBe(false);
    });

    // Regression: the sign reveals only once recitation has PASSED its last
    // letter — not while that letter is still being recited, and not when the
    // word first becomes active. With the last letter 'c' ACTIVE the word is
    // active but the mark must stay dim; once 'c' is reached the mark reveals.
    it('reveals the waqf mark only after its letter is reached, not while active', async () => {
        const mid = render(LineAnimation, {
            units: [stopUnit()],
            config: charConfig,
            getTimeMs: () => 2500, // 'c' (last) ACTIVE, not yet reached
            playing: false,
        });
        await tick();
        const markMid = mid.container.querySelector<HTMLElement>('.ra-waqf-mark');
        // The word IS active (its last letter is being recited), yet the mark
        // stays un-revealed — the sign hasn't been passed yet.
        expect(markMid?.closest('.ra-word')?.classList.contains('active')).toBe(true);
        expect(markMid?.classList.contains('revealed')).toBe(false);

        const after = render(LineAnimation, {
            units: [stopUnit(), trailingUnit()],
            config: charConfig,
            getTimeMs: () => 3500, // trailing word active → stop word + 'c' reached
            playing: false,
        });
        await tick();
        const markAfter = after.container.querySelector<HTMLElement>('.ra-waqf-mark');
        expect(markAfter?.classList.contains('revealed')).toBe(true);
    });
});
