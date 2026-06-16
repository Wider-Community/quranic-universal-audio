import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it } from 'vitest';

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

    // Regression: the waqf (stop) sign is a SEPARATE clipped overlay, decoupled
    // from the letters — it must not perturb the per-letter reveal (the old
    // full-word occlusion layer bled extra ink, so a stop-sign word rendered
    // brighter / lit whole). Here the clean chars reveal exactly as if no mark
    // were present, and the mark overlay is never given the reveal highlight.
    it('renders the waqf mark as a separate overlay that never takes the reveal', async () => {
        const WAQF = 'ۖ'; // ARABIC SMALL HIGH SAD-LAM-ALEF-MEEM (a surfaced stop)
        const units = [
            unit('1:1:1', 'ab' + WAQF, 0, 2, [
                { char: 'a', start: 0, end: 1 },
                { char: 'b', start: 1, end: 2 },
            ]),
        ];

        const { container } = render(LineAnimation, {
            units,
            config: charConfig,
            getTimeMs: () => 1500,
            playing: false,
        });
        await tick();

        // Per-letter reveal is unperturbed: the mark is stripped from `clean`, so
        // the chars are exactly 'a','b' with 'a' reached and 'b' active at t=1.5s.
        const chars = container.querySelectorAll<HTMLElement>('.ra-char');
        expect([...chars].map((c) => c.textContent)).toEqual(['a', 'b']);
        expect(chars[0]?.classList.contains('reached')).toBe(true);
        expect(chars[1]?.classList.contains('active')).toBe(true);

        // The mark is one separate overlay carrying clean+mark, never a `.ra-char`
        // and never given the reveal highlight; it reveals with its last letter.
        const marks = container.querySelectorAll<HTMLElement>('.ra-waqf-mark');
        expect(marks.length).toBe(1);
        expect(marks[0]?.textContent).toBe('ab' + WAQF);
        expect(marks[0]?.classList.contains('active')).toBe(false);
        expect(marks[0]?.classList.contains('revealed')).toBe(true);
        expect(marks[0]?.classList.contains('waqf-active')).toBe(false);
    });
});
