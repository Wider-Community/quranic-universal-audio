/**
 * UnifiedDisplay cross-word bridge rendering tests.
 *
 * Pins the bridge-tile resolution for consecutive idgham boundaries where a
 * dissolving middle word (e.g. 28:86 مِّن) keeps only its haraka. MFA can place
 * the first boundary's merger phoneme on EITHER side of the مِّن boundary; the
 * second boundary must still resolve to its own merger and never re-use the
 * first boundary's tile (the "double-m̃" bug).
 */
import { cleanup, render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { dashPort } from '../../../../lib/playback/dash-port';
import { makeAudioStub as makePortAudioStub } from '../../../../lib/playback/__tests__/raf-harness';
import type { BridgeInfo } from '../../../../lib/types/generated/schemas';
import type { Letter, PhonemeInterval, TsVerseData, TsWord } from '../../../../lib/types/domain';
import { loadedTajweedBridges, loadedVerse } from '../../stores/verse';

import UnifiedDisplay from '../UnifiedDisplay.svelte';

interface Ph {
    sym: string;
    start: number;
    end: number;
}

function word(wordNum: number, indices: number[], letters: string): TsWord {
    const ls: Letter[] = [...letters].map((c) => ({ char: c, start: null, end: null }));
    return {
        location: `28:86:${wordNum}`,
        text: letters,
        display_text: letters,
        start: 0,
        end: 1,
        phoneme_indices: indices,
        letters: ls,
    };
}

function intervals(phs: Ph[]): PhonemeInterval[] {
    return phs.map((p) => ({ phone: p.sym, start: p.start, end: p.end }));
}

function mount(words: TsWord[], ivals: PhonemeInterval[], bridges: BridgeInfo[]) {
    const data: TsVerseData = {
        reciter: 'ayman_swed_muallim_tvquran',
        chapter: 28,
        verse_ref: '28:86',
        audio_url: 'http://audio/28.mp3',
        audio_category: 'by_surah_audio',
        time_start_ms: 0,
        time_end_ms: 999_999,
        intervals: ivals,
        words,
    };
    loadedVerse.set({ data, tsSegOffset: 0, tsSegEnd: 999 });
    loadedTajweedBridges.set(bridges);
    return render(UnifiedDisplay);
}

/** Walk the rendered DOM in document order, returning a flat sequence of
 *  `{kind:'bridge', text}` and `{kind:'word', loc, phon}` entries. */
function readSequence(container: HTMLElement) {
    const root = container.querySelector('.unified-display')!;
    const seq: Array<{ kind: string; text?: string; phon?: string[] }> = [];
    for (const el of Array.from(root.children)) {
        if (el.classList.contains('crossword-bridge')) {
            const text = Array.from(el.querySelectorAll('.mega-phoneme'))
                .map((s) => s.textContent!.trim())
                .join(' ');
            seq.push({ kind: 'bridge', text });
        } else if (el.classList.contains('mega-block')) {
            const phon = Array.from(el.querySelectorAll('.mega-phonemes .mega-phoneme')).map((s) =>
                s.textContent!.trim(),
            );
            seq.push({ kind: 'word', phon });
        }
    }
    return seq;
}

const BRIDGES: BridgeInfo[] = [
    { before_word_idx: 10, rule: 'idgham_ghunnah_tanween', side: 'curr' },
    { before_word_idx: 11, rule: 'idgham_bila_ghunnah_noon', side: 'curr' },
];

describe('UnifiedDisplay — consecutive idgham bridges around a dissolving word (28:86)', () => {
    beforeEach(() => {
        dashPort.attachElement(
            makePortAudioStub({ src: 'http://audio/28.mp3', readyState: 4 }) as unknown as HTMLAudioElement,
        );
        dashPort.setSource({ audioUrl: 'http://audio/28.mp3', reciter: null, vbr: false });
    });
    afterEach(() => {
        cleanup();
        loadedVerse.set(null);
        loadedTajweedBridges.set([]);
        dashPort.attachElement(null);
    });

    it('layout A — m̃ in رحمة tail (prev), من keeps only its kasra', () => {
        const ivals = intervals([
            { sym: 'rˤ', start: 2713.985, end: 2714.225 }, // 0  رحمة
            { sym: 'aˤ', start: 2714.225, end: 2714.315 }, // 1
            { sym: 'ħ', start: 2714.315, end: 2714.765 }, // 2
            { sym: 'm', start: 2714.765, end: 2714.775 }, // 3
            { sym: 'a', start: 2714.775, end: 2714.925 }, // 4
            { sym: 't', start: 2714.925, end: 2715.085 }, // 5
            { sym: 'a', start: 2715.085, end: 2715.285 }, // 6
            { sym: 'm̃', start: 2715.285, end: 2716.425 }, // 7  bridge1
            { sym: 'i', start: 2716.425, end: 2716.535 }, // 8  من
            { sym: 'rˤrˤ', start: 2716.535, end: 2716.995 }, // 9  bridge2
            { sym: 'aˤ', start: 2716.995, end: 2717.095 }, // 10 ربك
            { sym: 'bb', start: 2717.095, end: 2717.485 }, // 11
            { sym: 'i', start: 2717.485, end: 2717.785 }, // 12
            { sym: 'k', start: 2717.785, end: 2718.225 }, // 13
        ]);
        const words = [
            word(9, [0, 1, 2, 3, 4, 5, 6, 7], 'رحمة'),
            word(10, [8], 'من'),
            word(11, [9, 10, 11, 12, 13], 'ربك'),
        ];
        const { container } = mount(words, ivals, BRIDGES);
        const seq = readSequence(container as HTMLElement);
        const bridges = seq.filter((s) => s.kind === 'bridge').map((s) => s.text);
        const wordsArr = seq.filter((s) => s.kind === 'word');
        expect(bridges).toEqual(['m̃', 'rˤrˤ']);
        expect(wordsArr[1]!.phon).toEqual(['i']); // مِّن keeps its surviving kasra
        expect(wordsArr[2]!.phon).toEqual(['aˤ', 'bb', 'i', 'k']); // ربك without the rˤrˤ bridge
    });

    it('layout B — m̃ in من head (curr), then kasra: 2nd boundary must NOT re-use m̃', () => {
        const ivals = intervals([
            { sym: 'rˤ', start: 2713.985, end: 2714.225 }, // 0  رحمة
            { sym: 'aˤ', start: 2714.225, end: 2714.315 }, // 1
            { sym: 'ħ', start: 2714.315, end: 2714.765 }, // 2
            { sym: 'm', start: 2714.765, end: 2714.775 }, // 3
            { sym: 'a', start: 2714.775, end: 2714.925 }, // 4
            { sym: 't', start: 2714.925, end: 2715.085 }, // 5
            { sym: 'a', start: 2715.085, end: 2715.285 }, // 6
            { sym: 'm̃', start: 2715.285, end: 2716.425 }, // 7  bridge1 (now in من head)
            { sym: 'i', start: 2716.425, end: 2716.535 }, // 8  من kasra
            { sym: 'rˤrˤ', start: 2716.535, end: 2716.995 }, // 9  bridge2
            { sym: 'aˤ', start: 2716.995, end: 2717.095 }, // 10 ربك
            { sym: 'bb', start: 2717.095, end: 2717.485 }, // 11
            { sym: 'i', start: 2717.485, end: 2717.785 }, // 12
            { sym: 'k', start: 2717.785, end: 2718.225 }, // 13
        ]);
        const words = [
            word(9, [0, 1, 2, 3, 4, 5, 6], 'رحمة'),
            word(10, [7, 8], 'من'),
            word(11, [9, 10, 11, 12, 13], 'ربك'),
        ];
        const { container } = mount(words, ivals, BRIDGES);
        const seq = readSequence(container as HTMLElement);
        const bridges = seq.filter((s) => s.kind === 'bridge').map((s) => s.text);
        const wordsArr = seq.filter((s) => s.kind === 'word');
        expect(bridges).toEqual(['m̃', 'rˤrˤ']); // NOT ['m̃','m̃']
        expect(wordsArr[1]!.phon).toEqual(['i']); // مِّن keeps its surviving kasra
        expect(wordsArr[2]!.phon).toEqual(['aˤ', 'bb', 'i', 'k']); // rˤrˤ must be lifted out
    });
});
