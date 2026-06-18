/**
 * UnifiedDisplay — non-recited section markers are stripped from the word box.
 *
 * The rub-el-hizb (۞ U+06DE) and place-of-sajdah (۩ U+06E9) are notation, not
 * recited letters; they must not appear in the analysis word cell (`.mega-word`).
 */
import { cleanup, render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { dashPort } from '../../../../lib/playback/dash-port';
import { makeAudioStub as makePortAudioStub } from '../../../../lib/playback/__tests__/raf-harness';
import type { Letter, TsVerseData, TsWord } from '../../../../lib/types/ts-client';
import { loadedVerse } from '../../stores/verse';

import UnifiedDisplay from '../UnifiedDisplay.svelte';

const RUB = String.fromCodePoint(0x06de);
const SAJDAH = String.fromCodePoint(0x06e9);
const BASE = String.fromCodePoint(0x627, 0x628, 0x62c); // alef-ba-jeem

function word(display: string, letters: string): TsWord {
    const ls: Letter[] = [...letters].map((c) => ({ char: c, start: 0, end: 1 }));
    return {
        location: '7:206:1',
        text: display,
        display_text: display,
        start: 0,
        end: 1,
        phoneme_indices: [],
        letters: ls,
    };
}

function mount(words: TsWord[]) {
    const data: TsVerseData = {
        reciter: 'mishary_rashid_al_afasy_mp3quran',
        chapter: 7,
        verse_ref: '7:206',
        audio_url: 'http://audio/7.mp3',
        audio_category: 'by_surah_audio',
        time_start_ms: 0,
        time_end_ms: 999_999,
        intervals: [],
        words,
    };
    loadedVerse.set({ data, tsSegOffset: 0, tsSegEnd: 999 });
    return render(UnifiedDisplay);
}

describe('UnifiedDisplay — non-recited section markers', () => {
    beforeEach(() => {
        dashPort.attachElement(
            makePortAudioStub({ src: 'http://audio/7.mp3', readyState: 4 }) as unknown as HTMLAudioElement,
        );
        dashPort.setSource({ audioUrl: 'http://audio/7.mp3', reciter: null, vbr: false });
    });
    afterEach(() => {
        cleanup();
        loadedVerse.set(null);
        dashPort.attachElement(null);
    });

    it('strips rub-el-hizb and sajdah from the analysis word box', () => {
        const { container } = mount([word(RUB + BASE + SAJDAH, BASE)]);
        const box = container.querySelector('.mega-word')!;
        expect(box.textContent).toBe(BASE);
        expect(box.textContent).not.toContain(RUB);
        expect(box.textContent).not.toContain(SAJDAH);
    });
});
