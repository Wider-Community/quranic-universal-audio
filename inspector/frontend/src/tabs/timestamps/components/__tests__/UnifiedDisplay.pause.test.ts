/**
 * UnifiedDisplay pause-bridge rendering tests.
 *
 * A detected inter-word silence (a positive gap between consecutive words, whose
 * ms-quantized end/start are otherwise contiguous) renders a small pause bridge
 * between the two word columns. When the earlier word carries a surfaced waqf
 * (stop) mark, the mark is lifted out of its box into the bridge; otherwise the
 * bridge shows the neutral pause icon.
 */
import { cleanup, render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { dashPort } from '../../../../lib/playback/dash-port';
import { makeAudioStub as makePortAudioStub } from '../../../../lib/playback/__tests__/raf-harness';
import type { Letter, TsVerseData, TsWord } from '../../../../lib/types/ts-client';
import { tsWaveformHoverTime } from '../../stores/display';
import { loadedVerse } from '../../stores/verse';

import UnifiedDisplay from '../UnifiedDisplay.svelte';

const SALA = 'ۖ'; // surfaced permissible-stop mark

function word(wordNum: number, text: string, start: number, end: number): TsWord {
    const ls: Letter[] = [...text].map((c) => ({ char: c, start: null, end: null }));
    return {
        location: `2:2:${wordNum}`,
        text,
        display_text: text,
        start,
        end,
        phoneme_indices: [],
        letters: ls,
    };
}

function mount(words: TsWord[]) {
    const data: TsVerseData = {
        reciter: 'r',
        chapter: 2,
        verse_ref: '2:2',
        audio_url: 'http://audio/2.mp3',
        audio_category: 'by_surah_audio',
        time_start_ms: 0,
        time_end_ms: 999_999,
        intervals: [],
        words,
    };
    loadedVerse.set({ data, tsSegOffset: 0, tsSegEnd: 999 });
    return render(UnifiedDisplay);
}

describe('UnifiedDisplay — pause bridges', () => {
    beforeEach(() => {
        dashPort.attachElement(
            makePortAudioStub({ src: 'http://audio/2.mp3', readyState: 4 }) as unknown as HTMLAudioElement,
        );
        dashPort.setSource({ audioUrl: 'http://audio/2.mp3', reciter: null, vbr: false });
    });
    afterEach(() => {
        cleanup();
        loadedVerse.set(null);
        tsWaveformHoverTime.set(null);
        dashPort.attachElement(null);
    });

    it('lifts a stop sign out of the word box into the bridge across a silence', () => {
        const { container } = mount([
            word(1, `فمن${SALA}`, 0, 1), // ends with a waqf mark, then a pause
            word(2, 'بعد', 1.5, 2.5), // 0.5s gap
        ]);
        const bridge = container.querySelector('.pause-bridge')!;
        expect(bridge).not.toBeNull();
        expect(bridge.querySelector('.pause-waqf')!.textContent).toBe(SALA);
        // The mark is gone from the first word's box.
        const firstWord = container.querySelectorAll('.mega-word')[0]!;
        expect(firstWord.textContent).toBe('فمن');
        expect(firstWord.textContent).not.toContain(SALA);
        // The pause span carries the silence window for the per-frame highlight.
        expect(bridge.getAttribute('data-pause-start')).toBe('1');
        expect(bridge.getAttribute('data-pause-end')).toBe('1.5');
    });

    it('shows the neutral pause icon when the silence has no stop sign', () => {
        const { container } = mount([
            word(1, 'فمن', 0, 1),
            word(2, 'بعد', 1.5, 2.5),
        ]);
        const bridge = container.querySelector('.pause-bridge')!;
        expect(bridge.querySelector('.pause-icon')).not.toBeNull();
        expect(bridge.querySelector('.pause-waqf')).toBeNull();
    });

    it('renders no bridge between contiguous words (no detected silence)', () => {
        const { container } = mount([
            word(1, `فمن${SALA}`, 0, 1),
            word(2, 'بعد', 1, 2), // contiguous — same boundary
        ]);
        expect(container.querySelector('.pause-bridge')).toBeNull();
        // With no surfacing pause, the mark stays in the word box.
        expect(container.querySelectorAll('.mega-word')[0]!.textContent).toBe(`فمن${SALA}`);
    });

    it('dims the row (.in-pause) during the trailing end-of-verse silence', async () => {
        const { container } = mount([
            word(1, 'فمن', 0, 1),
            word(2, 'بعد', 1, 2.5), // contiguous — no inter-word pause-bridge
        ]);
        const root = container.querySelector('.unified-display')!;
        // Paused hover past the last recited word → the verse-end waqf silence.
        tsWaveformHoverTime.set(3.0);
        await tick();
        expect(root.classList.contains('in-pause')).toBe(true);
        // Hover within a recited word → no dim.
        tsWaveformHoverTime.set(0.5);
        await tick();
        expect(root.classList.contains('in-pause')).toBe(false);
    });
});
