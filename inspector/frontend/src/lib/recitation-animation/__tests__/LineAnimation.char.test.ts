import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it } from 'vitest';

import chapterTwoShapedJson from '../../../../public/generated/shaped-glyphs-v13/2.json?raw';
import shapedPathsJson from '../../../../public/generated/shaped-glyphs-v13/paths.json?raw';

import { ZWSP } from '../../utils/arabic-text';
import { DEFAULT_RECITATION_CONFIG } from '../config';
import lineAnimationSource from '../LineAnimation.svelte?raw';
import LineAnimation from '../LineAnimation.svelte';
import type { ShapedGlyphFixture } from '../shaped-glyphs';
import type { AnimUnit } from '../types';

const shapedGlyphs = {
    ...JSON.parse(chapterTwoShapedJson),
    paths: JSON.parse(shapedPathsJson).paths,
} as ShapedGlyphFixture;

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

    it('reveals a silent timing borrower without giving it the active colour', async () => {
        const units = [
            unit('1:1:1', 'ab', 0, 1, [
                { char: 'a', start: 0, end: 1, tokenId: 0, silent: false },
                { char: 'b', start: 0, end: 1, tokenId: 1, silent: true },
            ]),
        ];

        const normal = render(LineAnimation, {
            units,
            config: charConfig,
            getTimeMs: () => 500,
            playing: false,
            omitSilentHighlights: false,
        });
        await tick();
        expect([...normal.container.querySelectorAll('.ra-char')].map((char) => ({
            active: char.classList.contains('active'),
            reached: char.classList.contains('reached'),
        }))).toEqual([
            { active: true, reached: false },
            { active: true, reached: false },
        ]);
        normal.unmount();

        const omitted = render(LineAnimation, {
            units,
            config: charConfig,
            getTimeMs: () => 500,
            playing: false,
            omitSilentHighlights: true,
        });
        await tick();
        expect([...omitted.container.querySelectorAll('.ra-char')].map((char) => ({
            active: char.classList.contains('active'),
            reached: char.classList.contains('reached'),
        }))).toEqual([
            { active: true, reached: false },
            { active: false, reached: true },
        ]);
        expect(omitted.container.querySelector('.ra-word')?.classList.contains('active')).toBe(true);
        omitted.unmount();

        const full = render(LineAnimation, {
            units,
            config: { ...charConfig, unreachedOpacity: 1 },
            getTimeMs: () => 500,
            playing: false,
            omitSilentHighlights: true,
        });
        await tick();
        expect([...full.container.querySelectorAll('.ra-char')].map((char) => ({
            active: char.classList.contains('active'),
            reached: char.classList.contains('reached'),
        }))).toEqual([
            { active: true, reached: false },
            { active: false, reached: false },
        ]);
    });

    it('paints an iqlab mini-meem without repainting its silent noon host', async () => {
        const iqlab = unit('104:4:2', 'لَيُنۢبَذَنَّ', 0, 1, [
            { char: 'ن', start: 0, end: 1, tokenId: 0, silent: false },
        ]);
        const iqlabGlyphs: ShapedGlyphFixture = {
            upem: 1000,
            paths: { meemiqlab: '', onedotup: '', 'behshape.medi.beforeseen': '' },
            words: {
                'لَيُنۢبَذَنَّ': {
                    baseText: 'لَيُنۢبَذَنَّ',
                    advance: 1000,
                    tokenCount: 1,
                    placements: [
                        ['meemiqlab', 0, 0, 0, null],
                        ['onedotup', 0, 0, 0, 'silent_companion'],
                        ['behshape.medi.beforeseen', 0, 0, 0, 'silent_companion'],
                    ],
                },
            },
        };

        const normal = render(LineAnimation, {
            units: [iqlab],
            config: charConfig,
            getTimeMs: () => 500,
            playing: false,
            omitSilentHighlights: false,
            shapedGlyphs: iqlabGlyphs,
        });
        await tick();
        expect(normal.container.querySelector('.ra-line')?.classList.contains('ra-omit-silent')).toBe(false);
        expect(normal.container.querySelectorAll('.ra-shaped-token.active path')).toHaveLength(3);
        normal.unmount();

        const { container } = render(LineAnimation, {
            units: [iqlab],
            config: charConfig,
            getTimeMs: () => 500,
            playing: false,
            omitSilentHighlights: true,
            shapedGlyphs: iqlabGlyphs,
        });
        await tick();

        const line = container.querySelector('.ra-line');
        const active = container.querySelector('.ra-shaped-token.active');
        expect(line?.classList.contains('ra-omit-silent')).toBe(true);
        expect(line?.classList.contains('ra-full-opacity')).toBe(false);
        expect(active?.querySelectorAll('path:not(.ra-silent-companion)')).toHaveLength(1);
        expect(active?.querySelectorAll('path.ra-silent-companion')).toHaveLength(2);
        expect(lineAnimationSource).toMatch(
            /\.ra-line\.ra-omit-silent[^}]*\.ra-silent-companion\s*\{[^}]*fill:\s*var\(--ra-base-color\)/,
        );
        expect(lineAnimationSource).toMatch(
            /\.ra-line\.ra-full-opacity\.ra-omit-silent[^}]*\.ra-silent-companion\s*\{[^}]*display:\s*none/,
        );
    });

    it('keeps the 21:88 small waw active independently without glow spill onto haa', async () => {
        const lahu = unit('21:88:2', 'لَهُۥ', 0, 3, [
            { char: 'ل', start: 0, end: 1, tokenId: 0 },
            { char: 'ه', start: 1, end: 2, tokenId: 1 },
            { char: 'ۥ', start: 2, end: 3, tokenId: 2 },
        ]);
        const lahuGlyphs: ShapedGlyphFixture = {
            upem: 1000,
            paths: { lam: '', haa: '', smallwaw: '' },
            words: {
                'لَهُۥ': {
                    baseText: 'لَهُۥ', advance: 1000, tokenCount: 3,
                    placements: [
                        ['lam', 0, 0, 0, null],
                        ['haa', 0, 0, 1, null],
                        ['smallwaw', 0, 0, 2, null],
                    ],
                },
            },
        };
        const { container } = render(LineAnimation, {
            units: [lahu], config: charConfig, getTimeMs: () => 2500,
            playing: false, shapedGlyphs: lahuGlyphs,
        });
        await tick();

        const haa = container.querySelector('.ra-shaped-token[data-token-text="ه"]');
        const waw = container.querySelector('.ra-shaped-token[data-token-text="ۥ"]');
        expect(haa?.classList.contains('active')).toBe(false);
        expect(waw?.classList.contains('active')).toBe(true);
        expect(waw?.getAttribute('data-mark-only')).toBe('true');
        expect(lineAnimationSource).toMatch(
            /\.ra-shaped-token\[data-mark-only="true"\]:global\(\.active\)\s*\{[^}]*filter:\s*none/,
        );
    });

    it('keeps the repeated 21:88 small-waw token separate from its haa host', async () => {
        const firstTake = [
            { char: 'ل', start: 0, end: 1, tokenId: 0 },
            { char: 'ه', start: 1, end: 2, tokenId: 1 },
            { char: 'ۥ', start: 2, end: 3, tokenId: 2 },
        ];
        const secondTake = [
            { char: 'ل', start: 10, end: 11, tokenId: 0 },
            { char: 'ه', start: 11, end: 12, tokenId: 1 },
            { char: 'ۥ', start: 12, end: 13, tokenId: 2 },
        ];
        const repeated: AnimUnit = {
            ...unit('21:88:2', 'لَهُۥ', 0, 13, firstTake),
            intervals: [{ start: 0, end: 3 }, { start: 10, end: 13 }],
            occurrenceLetters: [firstTake, secondTake],
        };

        for (const omitSilentHighlights of [false, true]) {
            const { container, unmount } = render(LineAnimation, {
                units: [repeated], config: charConfig, getTimeMs: () => 12_500,
                playing: false, omitSilentHighlights,
            });
            await tick();

            const tokens = container.querySelectorAll('.ra-char');
            expect(tokens[1]?.textContent).toBe('ه');
            expect(tokens[2]?.textContent).toBe('ۥ');
            expect(tokens[1]?.classList.contains('active')).toBe(false);
            expect(tokens[2]?.classList.contains('active')).toBe(true);
            unmount();
        }
    });

    // Regression: cross-word co-timed letters must re-light on a loopback. The
    // active word remaps the repeat occurrence onto its canonical timeline; the
    // co-timed letter in the PREVIOUS word must follow the same remapped time,
    // not raw playback time (which overshoots the canonical interval on a repeat
    // and drops the letter to `reached`).
    it('re-lights cross-word co-timed letters on a loopback repeat', async () => {
        const wordA = unit('1:1:1', 'ab', 0, 2, [
            { char: 'a', start: 0, end: 1 },
            { char: 'b', start: 1, end: 2 }, // co-timed with word B's 'c'
        ]);
        const wordB: AnimUnit = {
            location: '1:1:2',
            ayahKey: '1:1',
            surah: 1,
            ayah: 1,
            word: 2,
            text: 'cd',
            start: 1,
            end: 7,
            // Canonical occurrence [1,3] plus a repeat at [5,7]; the letters stay
            // anchored to the canonical span.
            intervals: [
                { start: 1, end: 3 },
                { start: 5, end: 7 },
            ],
            letters: [
                { char: 'c', start: 1, end: 2 },
                { char: 'd', start: 2, end: 3 },
            ],
        };

        const { container } = render(LineAnimation, {
            units: [wordA, wordB],
            config: charConfig,
            getTimeMs: () => 5500, // inside B's repeat [5,7] → localT remaps to 1.5s
            playing: false,
        });
        await tick();

        const chars = container.querySelectorAll<HTMLElement>('.ra-char');
        expect(chars[1]?.textContent).toBe('b');
        expect(chars[2]?.textContent).toBe('c');
        // 'c' is the active word's letter at the remapped time; 'b' is its
        // cross-word co-timed neighbour in the previous word — both light on the
        // repeat, exactly as they do on the first pass.
        expect(chars[2]?.classList.contains('active')).toBe(true);
        expect(chars[1]?.classList.contains('active')).toBe(true);
    });

    // Regression: a repeated verse reveals at the CURRENT take's own pace, not a
    // linear stretch of take 1. Take 1 is even (a,b each 1s); take 2 elongates
    // 'a' (melodic madd) so the letters are NOT proportional to take 1. With the
    // old remap, t mid-take-2 mapped to take-1 proportions and lit the FUTURE
    // letter 'b'; the per-occurrence timings keep 'a' active while it is sounding.
    it('reveals a repeat at the take’s own letter pace, not a stretch of take 1', async () => {
        const repeated: AnimUnit = {
            location: '1:1:1',
            ayahKey: '1:1',
            surah: 1,
            ayah: 1,
            word: 1,
            text: 'ab',
            start: 0,
            end: 20,
            intervals: [
                { start: 0, end: 2 }, // take 1 (even)
                { start: 10, end: 20 }, // take 2 (a elongated)
            ],
            letters: [
                { char: 'a', start: 0, end: 1 },
                { char: 'b', start: 1, end: 2 },
            ],
            occurrenceLetters: [
                [
                    { char: 'a', start: 0, end: 1 },
                    { char: 'b', start: 1, end: 2 },
                ],
                [
                    { char: 'a', start: 10, end: 18 }, // front-heavy: 'a' holds to 18s
                    { char: 'b', start: 18, end: 20 },
                ],
            ],
        };

        const { container } = render(LineAnimation, {
            units: [repeated],
            config: charConfig,
            getTimeMs: () => 15000, // inside take 2; 'a' is still sounding [10,18]
            playing: false,
        });
        await tick();

        const chars = container.querySelectorAll<HTMLElement>('.ra-char');
        expect(chars[0]?.textContent).toBe('a');
        expect(chars[1]?.textContent).toBe('b');
        // 'a' is the letter being recited at 15s on take 2 — NOT 'b' (which the
        // old take-1-proportion remap would have lit).
        expect(chars[0]?.classList.contains('active')).toBe(true);
        expect(chars[1]?.classList.contains('active')).toBe(false);
    });

    it('keeps one SVG paint source before, during, and after a shaped word is active', async () => {
        const shaped = unit('2:2:1', 'ذَٰلِكَ', 0, 4, [
            { char: 'ذ', start: 0, end: 1 },
            { char: 'ٰ', start: 1, end: 2 },
            { char: 'ل', start: 2, end: 3 },
            { char: 'ك', start: 3, end: 4 },
        ]);
        const trailing = unit('2:2:2', 'ٱلْكِتَٰبُ', 4, 5, [
            { char: 'ٱ', start: 4, end: 5 },
        ]);
        const fullConfig = { ...charConfig, unreachedOpacity: 1 };

        async function paintAt(ms: number): Promise<{ ruler: string; tokens: number }> {
            const { container, unmount } = render(LineAnimation, {
                units: [shaped, trailing],
                config: fullConfig,
                getTimeMs: () => ms,
                playing: false,
                shapedGlyphs,
            });
            await tick();
            const word = container.querySelector<HTMLElement>('.ra-word[data-start="0"]');
            const ruler = word?.querySelector<HTMLElement>('.ra-shaped-base-text');
            const tokens = [...(word?.querySelectorAll<SVGElement>('.ra-shaped-token') ?? [])];
            const result = {
                ruler: ruler?.style.visibility ?? 'missing',
                tokens: tokens.length,
            };
            unmount();
            return result;
        }

        const future = await paintAt(-100);
        const active = await paintAt(1500);
        const reached = await paintAt(4500);

        // The native text is a permanently invisible layout ruler. Every glyph
        // is always painted by the SVG, so entering/leaving activity cannot swap
        // rasterizers, baselines, or apparent weight.
        expect([future.ruler, active.ruler, reached.ruler]).toEqual(['hidden', 'hidden', 'hidden']);
        expect([future.tokens, active.tokens, reached.tokens]).toEqual([4, 4, 4]);
    });

    it('keeps one joined dim silhouette underneath an active shaped word', async () => {
        const shaped = unit('2:2:1', 'ذَٰلِكَ', 0, 4, [
            { char: 'ذ', start: 0, end: 1 },
            { char: 'ٰ', start: 1, end: 2 },
            { char: 'ل', start: 2, end: 3 },
            { char: 'ك', start: 3, end: 4 },
        ]);

        const { container } = render(LineAnimation, {
            units: [shaped],
            config: { ...charConfig, unreachedOpacity: 0.2 },
            getTimeMs: () => 1500,
            playing: false,
            shapedGlyphs,
        });
        await tick();

        const word = container.querySelector<HTMLElement>('.ra-word');
        const base = word?.querySelector<SVGGElement>('.ra-shaped-base-layer');
        const tokens = [...(word?.querySelectorAll<SVGGElement>('.ra-shaped-token') ?? [])];

        expect(word?.classList.contains('active')).toBe(true);
        expect(base).not.toBeNull();
        expect(base?.querySelectorAll('path').length).toBeGreaterThan(0);
        expect(tokens.some((token) => !token.classList.contains('reached')
            && !token.classList.contains('active'))).toBe(true);
    });

    it('uses independently paintable dagger glyphs in the reported 2:5 and 2:9 words', async () => {
        const cases = [
            unit('2:5:1', 'أُو۟لَٰٓئِكَ', 0, 6, [
                { char: 'أ', start: 0, end: 1, tokenId: 0 },
                { char: 'و۟', start: 1, end: 2, tokenId: 1 },
                { char: 'ل', start: 2, end: 3, tokenId: 2 },
                { char: 'ٰٓ', start: 3, end: 4, tokenId: 3 },
                { char: 'ئ', start: 4, end: 5, tokenId: 4 },
                { char: 'ك', start: 5, end: 6, tokenId: 5 },
            ]),
            unit('2:9:1', 'يُخَٰدِعُونَ', 0, 7, [
                { char: 'ي', start: 0, end: 1, tokenId: 0 },
                { char: 'خ', start: 1, end: 2, tokenId: 1 },
                { char: 'ٰ', start: 2, end: 3, tokenId: 2 },
                { char: 'د', start: 3, end: 4, tokenId: 3 },
                { char: 'ع', start: 4, end: 5, tokenId: 4 },
                { char: 'و', start: 5, end: 6, tokenId: 5 },
                { char: 'ن', start: 6, end: 7, tokenId: 6 },
            ]),
        ];

        for (const shaped of cases) {
            const daggerIndex = shaped.letters.findIndex((letter) => letter.char.startsWith('ٰ'));
            const { container, unmount } = render(LineAnimation, {
                units: [shaped],
                config: charConfig,
                getTimeMs: () => (daggerIndex + 0.5) * 1000,
                playing: false,
                shapedGlyphs,
            });
            await tick();

            const word = container.querySelector<HTMLElement>('.ra-word');
            const dagger = word?.querySelector<SVGGElement>(
                `.ra-shaped-token[data-token-id="${daggerIndex}"]`,
            );
            expect(word?.querySelector('.ra-shaped-svg')).not.toBeNull();
            expect(dagger?.querySelectorAll('path').length).toBeGreaterThan(0);
            expect(dagger?.classList.contains('active')).toBe(true);
            unmount();
        }
    });

    it('does not repaint the complete shaped base when a word finishes', async () => {
        const shaped = unit('2:2:1', 'ذَٰلِكَ', 0, 4, [
            { char: 'ذ', start: 0, end: 1 },
            { char: 'ٰ', start: 1, end: 2 },
            { char: 'ل', start: 2, end: 3 },
            { char: 'ك', start: 3, end: 4 },
        ]);
        const trailing = unit('2:2:2', 'ٱلْكِتَٰبُ', 4, 5, [
            { char: 'ٱ', start: 4, end: 5 },
        ]);
        const { container } = render(LineAnimation, {
            units: [shaped, trailing],
            config: { ...charConfig, unreachedOpacity: 0.2 },
            getTimeMs: () => 4500,
            playing: false,
            shapedGlyphs,
        });
        await tick();

        const word = container.querySelector<HTMLElement>('.ra-word[data-start="0"]');
        const tokens = [...(word?.querySelectorAll<SVGGElement>('.ra-shaped-token') ?? [])];
        expect(word?.classList.contains('reached')).toBe(true);
        expect(tokens.every((token) => token.classList.contains('reached'))).toBe(true);
        // Token overlays already paint the completed word. Promoting the whole
        // base silhouette to opacity 1 underneath them double-paints every
        // glyph and creates the brightness/weight jump at the boundary.
        expect(lineAnimationSource).not.toMatch(
            /\.ra-line\.ra-chars \.ra-word:global\(\.reached\) \.ra-shaped-base-layer\s*\{[^}]*opacity:\s*1/,
        );
    });

    it('uses one paint layer for completed words in full-opacity letter mode', async () => {
        const shaped = unit('2:2:1', 'ذَٰلِكَ', 0, 4, [
            { char: 'ذ', start: 0, end: 1 },
            { char: 'ٰ', start: 1, end: 2 },
            { char: 'ل', start: 2, end: 3 },
            { char: 'ك', start: 3, end: 4 },
        ]);
        const trailing = unit('2:2:2', 'ٱلْكِتَٰبُ', 4, 5, [
            { char: 'ٱ', start: 4, end: 5 },
        ]);
        const { container } = render(LineAnimation, {
            units: [shaped, trailing],
            config: { ...charConfig, unreachedOpacity: 1 },
            getTimeMs: () => 4500,
            playing: false,
            shapedGlyphs,
        });
        await tick();

        const word = container.querySelector<HTMLElement>('.ra-word[data-start="0"]');
        expect(container.querySelector('.ra-line')?.classList.contains('ra-full-opacity')).toBe(true);
        expect(word?.classList.contains('reached')).toBe(true);
        expect(lineAnimationSource).toMatch(
            /\.ra-line\.ra-full-opacity\.ra-chars \.ra-shaped-token:global\(\.reached\):not\(:global\(\.active\)\)\s*\{[^}]*opacity:\s*0/,
        );
    });

    it('uses the same shaped word paint tree in word and letter modes', async () => {
        const shaped = unit('2:2:1', 'ذَٰلِكَ', 0, 4, [
            { char: 'ذ', start: 0, end: 1 },
            { char: 'ٰ', start: 1, end: 2 },
            { char: 'ل', start: 2, end: 3 },
            { char: 'ك', start: 3, end: 4 },
        ]);

        function paintTree(granularity: 'word' | 'char'): {
            svg: boolean;
            ruler: string;
            paths: number;
            stopMarks: number;
        } {
            const { container, unmount } = render(LineAnimation, {
                units: [shaped],
                config: { ...charConfig, granularity },
                getTimeMs: () => 1500,
                playing: false,
                shapedGlyphs,
            });
            const word = container.querySelector<HTMLElement>('.ra-word');
            const svg = word?.querySelector<SVGElement>('.ra-shaped-svg');
            const result = {
                svg: !!svg,
                ruler: word?.querySelector<HTMLElement>('.ra-shaped-base-text')?.style.visibility ?? 'missing',
                paths: svg?.querySelectorAll('path').length ?? 0,
                stopMarks: word?.querySelectorAll('.ra-decorator--waqf').length ?? 0,
            };
            unmount();
            return result;
        }

        const word = paintTree('word');
        const letter = paintTree('char');

        expect(word).toEqual(letter);
        expect(word.svg).toBe(true);
        expect(word.ruler).toBe('hidden');
        expect(word.paths).toBeGreaterThan(0);
        expect(word.stopMarks).toBe(0);
    });

    it('keeps the whole-word scale and fade motion out of letter mode', () => {
        expect(lineAnimationSource).toContain(
            'transform var(--ra-active-emphasis) var(--ra-easing)',
        );
        expect(lineAnimationSource).toMatch(
            /\.ra-line:not\(\.ra-chars\) \.ra-word:global\(\.active\)\s*\{[^}]*transform: scale\(var\(--ra-active-scale\)\);/,
        );
        expect(lineAnimationSource).not.toMatch(
            /\.ra-line\.ra-chars \.ra-shaped-token:global\(\.active\)\s*\{[^}]*transform:/,
        );
    });

    it('renders one shaped stop sign in either mode without a native duplicate', () => {
        const stopped = unit('2:2:4', 'رَيْبَۛ', 0, 3, [
            { char: 'ر', start: 0, end: 1 },
            { char: 'ي', start: 1, end: 2 },
            { char: 'ب', start: 2, end: 3 },
        ]);

        for (const granularity of ['word', 'char'] as const) {
            const { container, unmount } = render(LineAnimation, {
                units: [stopped],
                config: { ...charConfig, granularity },
                getTimeMs: () => 1500,
                playing: false,
                shapedGlyphs,
            });
            expect(container.querySelectorAll('.ra-decorator--waqf')).toHaveLength(1);
            unmount();
        }
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

        const marks = container.querySelectorAll<HTMLElement>('.ra-decorator--waqf');
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
        const markMid = mid.container.querySelector<HTMLElement>('.ra-decorator--waqf');
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
        const markAfter = after.container.querySelector<HTMLElement>('.ra-decorator--waqf');
        expect(markAfter?.classList.contains('revealed')).toBe(true);
    });

    // Inert non-recited symbols (rub-el-hizb, sajdah) render in place but never
    // take the highlight: at the moment its inherited interval would be active,
    // the symbol cell shows as reached, not active.
    it('never highlights an inert symbol cell (sajdah)', async () => {
        const SAJDAH = '۩';
        const { container } = render(LineAnimation, {
            units: [
                unit('1:1:1', 'ab' + SAJDAH, 0, 2, [
                    { char: 'a', start: 0, end: 1 },
                    { char: 'b', start: 1, end: 2 },
                ]),
            ],
            config: charConfig,
            getTimeMs: () => 1500, // 'b' active; the sajdah inherits b's interval
            playing: false,
        });
        await tick();
        const chars = [...container.querySelectorAll<HTMLElement>('.ra-char')];
        const b = chars.find((c) => c.textContent === 'b');
        const saj = chars.find((c) => c.textContent?.includes(SAJDAH));
        expect(b?.classList.contains('active')).toBe(true);
        expect(saj).toBeDefined();
        expect(saj?.classList.contains('active')).toBe(false);
    });
});
