/**
 * UnifiedDisplay silent-letter rendering tests.
 *
 * From shard schema v4 each letter carries a `silent` flag (phonemizer
 * `silent_flags()`). UnifiedDisplay renders every grapheme sharing a cell's
 * timing as its own `.lc` span and marks silent ones `.lc-silent`, so the
 * active-cell highlight reads on the pronounced letter alone.
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

    it('flags only the silent grapheme of a shared-timing cell with .lc-silent', () => {
        // ٱل share one cell (same timing): hamza wasl silent, lam sounding; ح is its own cell.
        const { container } = mount(
            word([
                { char: 'ٱ', start: 0, end: 0.2, silent: true },
                { char: 'ل', start: 0, end: 0.2, silent: false },
                { char: 'ح', start: 0.2, end: 0.4, silent: false },
            ]),
        );
        const cells = container.querySelectorAll('.mega-letter:not(.null-ts)');
        expect(cells.length).toBe(2);

        const firstParts = cells[0]!.querySelectorAll('.lc');
        expect(Array.from(firstParts).map((s) => s.textContent)).toEqual(['ٱ', 'ل']);
        expect(firstParts[0]!.classList.contains('lc-silent')).toBe(true);
        expect(firstParts[1]!.classList.contains('lc-silent')).toBe(false);

        const secondParts = cells[1]!.querySelectorAll('.lc');
        expect(Array.from(secondParts).map((s) => s.textContent)).toEqual(['ح']);
        expect(secondParts[0]!.classList.contains('lc-silent')).toBe(false);
    });
});
