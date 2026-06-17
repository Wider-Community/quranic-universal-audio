/**
 * UnifiedDisplay silent-letter rendering tests.
 *
 * From shard schema v4 each letter carries a `silent` flag (phonemizer
 * `silent_flags()`). UnifiedDisplay renders every grapheme as its own
 * `.mega-letter` cell (never grouped) and marks silent ones `.silent` — greyed,
 * non-interactive, and excluded from the highlight — so the highlight reads on
 * the pronounced letter that shares the timing alone.
 */
import { cleanup, render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { dashPort } from '../../../../lib/playback/dash-port';
import { makeAudioStub as makePortAudioStub } from '../../../../lib/playback/__tests__/raf-harness';
import type { Letter, TsVerseData, TsWord } from '../../../../lib/types/ts-client';
import { loadedVerse } from '../../stores/verse';

import UnifiedDisplay from '../UnifiedDisplay.svelte';

function word(letters: Letter[]): TsWord {
    const text = letters.map((l) => l.char).join('');
    return {
        location: '1:2:1',
        text,
        display_text: text,
        start: 0,
        end: 1,
        phoneme_indices: [],
        letters,
    };
}

function mount(w: TsWord) {
    const data: TsVerseData = {
        reciter: 'test',
        chapter: 1,
        verse_ref: '1:2',
        audio_url: 'http://audio/1.mp3',
        audio_category: 'by_surah_audio',
        time_start_ms: 0,
        time_end_ms: 999_999,
        intervals: [],
        words: [w],
    };
    loadedVerse.set({ data, tsSegOffset: 0, tsSegEnd: 999 });
    return render(UnifiedDisplay);
}

describe('UnifiedDisplay — silent-letter rendering', () => {
    beforeEach(() => {
        dashPort.attachElement(
            makePortAudioStub({ src: 'http://audio/1.mp3', readyState: 4 }) as unknown as HTMLAudioElement,
        );
        dashPort.setSource({ audioUrl: 'http://audio/1.mp3', reciter: null, vbr: false });
    });
    afterEach(() => {
        cleanup();
        loadedVerse.set(null);
        dashPort.attachElement(null);
    });

    it('renders every grapheme as its own cell and flags the silent one', () => {
        // ٱ and ل share timing but each is still its own cell (no grouping); the
        // hamza wasl is silent (greyed + inert), lam and ح sound.
        const { container } = mount(
            word([
                { char: 'ٱ', start: 0, end: 0.2, silent: true },
                { char: 'ل', start: 0, end: 0.2, silent: false },
                { char: 'ح', start: 0.2, end: 0.4, silent: false },
            ]),
        );
        const cells = container.querySelectorAll('.mega-letter:not(.null-ts)');
        // one cell per grapheme — NOT merged by shared timing
        expect(Array.from(cells).map((c) => c.textContent)).toEqual(['ٱ', 'ل', 'ح']);
        expect(cells[0]!.classList.contains('silent')).toBe(true); // hamza wasl
        expect(cells[1]!.classList.contains('silent')).toBe(false); // lam
        expect(cells[2]!.classList.contains('silent')).toBe(false); // ح
    });

    it('folds alef-maksura + dagger alef into one sounding cell', () => {
        // علىٰ: the aligner splits the dagger (ٰ) into its own shard letter, but
        // alef-maksura + dagger is one long-vowel unit → a single combined cell
        // spanning both timings, never split.
        const { container } = mount(
            word([
                { char: 'ع', start: 0, end: 0.1, silent: false },
                { char: 'ل', start: 0.1, end: 0.2, silent: false },
                { char: 'ى', start: 0.2, end: 0.3, silent: false },
                { char: 'ٰ', start: 0.3, end: 0.5, silent: false },
            ]),
        );
        const cells = container.querySelectorAll<HTMLElement>('.mega-letter:not(.null-ts)');
        expect(Array.from(cells).map((c) => c.textContent)).toEqual(['ع', 'ل', 'ىٰ']);
        const merged = cells[2]!;
        expect(merged.classList.contains('silent')).toBe(false);
        // spans maksura.start .. dagger.end
        expect(merged.dataset.letterStart).toBe('0.2');
        expect(merged.dataset.letterEnd).toBe('0.5');
    });

    it('keeps a carrier waw + dagger as two cells with the waw silent', () => {
        // صلوٰة: the waw is a silent seat; the dagger sounds. They stay separate
        // cells (only alef-maksura folds), and the waw alone is greyed.
        const { container } = mount(
            word([
                { char: 'ص', start: 0, end: 0.1, silent: false },
                { char: 'ل', start: 0.1, end: 0.2, silent: false },
                { char: 'و', start: 0.2, end: 0.3, silent: true },
                { char: 'ٰ', start: 0.3, end: 0.5, silent: false },
                { char: 'ة', start: 0.5, end: 0.6, silent: false },
            ]),
        );
        const cells = container.querySelectorAll<HTMLElement>('.mega-letter:not(.null-ts)');
        expect(Array.from(cells).map((c) => c.textContent)).toEqual(['ص', 'ل', 'و', 'ٰ', 'ة']);
        expect(cells[2]!.classList.contains('silent')).toBe(true); // carrier waw greyed
        expect(cells[3]!.classList.contains('silent')).toBe(false); // dagger sounds
    });
});
