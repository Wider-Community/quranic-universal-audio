/**
 * UnifiedDisplay cross-word bridge rendering tests.
 *
 * Bridges are baked into the shard: the merger phone carries a `bridge` rule
 * (schema v3). UnifiedDisplay lifts a tagged phone into the gold tile at the
 * boundary — a tag on a word's HEAD renders before that block, a tag in a
 * word's TAIL (idgham shafawi) bridges into the next block. These pin both
 * placements for the consecutive-idgham case around a dissolving middle word
 * (28:86 مِّن, whose م and ن both merge), where each boundary resolves to its
 * own tile and the inline rows keep only their surviving phones.
 */
import { cleanup, render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { dashPort } from '../../../../lib/playback/dash-port';
import { makeAudioStub as makePortAudioStub } from '../../../../lib/playback/__tests__/raf-harness';
import type { Letter, PhonemeInterval, TsCell, TsVerseData, TsWord } from '../../../../lib/types/ts-client';
import { loadedVerse } from '../../stores/verse';

import UnifiedDisplay from '../UnifiedDisplay.svelte';

interface Ph {
    sym: string;
    start: number;
    end: number;
    /** Cross-word bridge rule baked onto the merger phone. */
    bridge?: string;
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
    return phs.map((p) => ({
        phone: p.sym,
        start: p.start,
        end: p.end,
        ...(p.bridge ? { bridge: p.bridge } : {}),
    }));
}

function mount(words: TsWord[], ivals: PhonemeInterval[]) {
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
    return render(UnifiedDisplay);
}

/** Walk the rendered DOM in document order, returning a flat sequence of
 *  `{kind:'bridge', text}` and `{kind:'word', phon}` entries. */
function readSequence(container: HTMLElement) {
    const root = container.querySelector('.unified-display')!;
    const seq: Array<{ kind: string; text?: string; phon?: string[] }> = [];
    // Each `.word-unit` wraps an unbreakable run (words paired by a bridge or pause
    // connector); descend to its bridge/block parts in document order.
    const parts = Array.from(root.querySelectorAll('.word-unit')).flatMap((u) => Array.from(u.children));
    for (const el of parts) {
        if (el.classList.contains('crossword-bridge')) {
            const text = Array.from(el.querySelectorAll('.mega-phoneme'))
                .map((s) => s.textContent!.trim())
                .join(' ');
            seq.push({ kind: 'bridge', text });
        } else if (el.classList.contains('mega-block')) {
            const phon = Array.from(el.querySelectorAll('.mega-phoneme')).map((s) => s.textContent!.trim());
            seq.push({ kind: 'word', phon });
        }
    }
    return seq;
}

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
        dashPort.attachElement(null);
    });

    it('m̃ tagged in رحمة tail (prev) bridges into من; rˤrˤ tagged in ربك head', () => {
        const ivals = intervals([
            { sym: 'rˤ', start: 2713.985, end: 2714.225 }, // 0  رحمة
            { sym: 'aˤ', start: 2714.225, end: 2714.315 }, // 1
            { sym: 'ħ', start: 2714.315, end: 2714.765 }, // 2
            { sym: 'm', start: 2714.765, end: 2714.775 }, // 3
            { sym: 'a', start: 2714.775, end: 2714.925 }, // 4
            { sym: 't', start: 2714.925, end: 2715.085 }, // 5
            { sym: 'a', start: 2715.085, end: 2715.285 }, // 6
            { sym: 'm̃', start: 2715.285, end: 2716.425, bridge: 'idgham_ghunnah_tanween' }, // 7 bridge1 (prev tail)
            { sym: 'i', start: 2716.425, end: 2716.535 }, // 8  من kasra
            { sym: 'rˤrˤ', start: 2716.535, end: 2716.995, bridge: 'idgham_bila_ghunnah_noon' }, // 9 bridge2 (curr head)
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
        const { container } = mount(words, ivals);
        const seq = readSequence(container as HTMLElement);
        const bridges = seq.filter((s) => s.kind === 'bridge').map((s) => s.text);
        const wordsArr = seq.filter((s) => s.kind === 'word');
        expect(bridges).toEqual(['m̃', 'rˤrˤ']);
        expect(wordsArr[1]!.phon).toEqual(['i']); // مِّن keeps its surviving kasra
        // ربك without the rˤrˤ bridge; the heavy `aˤ` vowel DISPLAYS as plain `a`.
        expect(wordsArr[2]!.phon).toEqual(['a', 'bb', 'i', 'k']);
    });

    it('m̃ tagged in من head (curr) renders its own tile; rˤrˤ tile is never re-used', () => {
        const ivals = intervals([
            { sym: 'rˤ', start: 2713.985, end: 2714.225 }, // 0  رحمة
            { sym: 'aˤ', start: 2714.225, end: 2714.315 }, // 1
            { sym: 'ħ', start: 2714.315, end: 2714.765 }, // 2
            { sym: 'm', start: 2714.765, end: 2714.775 }, // 3
            { sym: 'a', start: 2714.775, end: 2714.925 }, // 4
            { sym: 't', start: 2714.925, end: 2715.085 }, // 5
            { sym: 'a', start: 2715.085, end: 2715.285 }, // 6
            { sym: 'm̃', start: 2715.285, end: 2716.425, bridge: 'idgham_ghunnah_tanween' }, // 7 bridge1 (من head)
            { sym: 'i', start: 2716.425, end: 2716.535 }, // 8  من kasra
            { sym: 'rˤrˤ', start: 2716.535, end: 2716.995, bridge: 'idgham_bila_ghunnah_noon' }, // 9 bridge2 (curr head)
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
        const { container } = mount(words, ivals);
        const seq = readSequence(container as HTMLElement);
        const bridges = seq.filter((s) => s.kind === 'bridge').map((s) => s.text);
        const wordsArr = seq.filter((s) => s.kind === 'word');
        expect(bridges).toEqual(['m̃', 'rˤrˤ']); // NOT ['m̃','m̃']
        expect(wordsArr[1]!.phon).toEqual(['i']); // مِّن keeps its surviving kasra
        // rˤrˤ lifted out; the heavy `aˤ` vowel DISPLAYS as plain `a`.
        expect(wordsArr[2]!.phon).toEqual(['a', 'bb', 'i', 'k']);
    });
});

const KASRA = 'ِ'; // U+0650

function cellWord(loc: string, letters: Letter[], cells: TsCell[], indices: number[]): TsWord {
    const text = letters.map((l) => l.char).join('');
    return { location: loc, text, display_text: text, start: 0, end: 1, phoneme_indices: indices, letters, cells };
}

describe('UnifiedDisplay — iltiqaa connecting-kasra borderless bridge', () => {
    beforeEach(() => {
        dashPort.attachElement(
            makePortAudioStub({ src: 'http://audio/28.mp3', readyState: 4 }) as unknown as HTMLAudioElement,
        );
        dashPort.setSource({ audioUrl: 'http://audio/28.mp3', reciter: null, vbr: false });
    });
    afterEach(() => {
        cleanup();
        loadedVerse.set(null);
        dashPort.attachElement(null);
    });

    it('lifts the inserted kasra (char + i phoneme) into a borderless bridge between the words', () => {
        // دٌ ٱل…  : tanwīn meets the next word's hamza-waṣl → connecting kasra (i).
        const ivals = intervals([
            { sym: 'd', start: 0, end: 0.1 }, // 0
            { sym: 'u', start: 0.1, end: 0.2 }, // 1 dammatan vowel
            { sym: 'n', start: 0.2, end: 0.3 }, // 2 dammatan nūn
            { sym: 'i', start: 0.3, end: 0.4 }, // 3 iltiqaa kasra (lifted)
            { sym: 'l', start: 0.4, end: 0.6 }, // 4 next word lām
        ]);
        const wN = cellWord('2:1:1', [{ char: 'د', start: 0, end: 0.3 }], [
            { chars: 'د', role: 'base', status: 'present', phonemeIndices: [0], sourceLetterIndex: 0, tag: null, shareGroup: null },
            { chars: 'ٌ', role: 'tanween', status: 'present', phonemeIndices: [1, 2], sourceLetterIndex: 0, tag: null, shareGroup: null },
            { chars: '', role: 'haraka', status: 'inserted', phonemeIndices: [3], sourceLetterIndex: 0, tag: 'iltiqaa_kasra', shareGroup: null },
        ], [0, 1, 2, 3]);
        const wNext = cellWord('2:1:2', [
            { char: 'ٱ', start: 0.4, end: 0.4 }, { char: 'ل', start: 0.4, end: 0.6 },
        ], [
            { chars: 'ٱ', role: 'base', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 0, tag: null, shareGroup: null },
            { chars: 'ل', role: 'base', status: 'present', phonemeIndices: [4], sourceLetterIndex: 1, tag: null, shareGroup: null },
        ], [4]);
        const { container } = mount([wN, wNext], ivals);

        const bridge = container.querySelector<HTMLElement>('.crossword-bridge.borderless')!;
        expect(bridge).toBeTruthy();
        // letter row: the kasra char, timed on the i interval.
        const letter = bridge.querySelector<HTMLElement>('.bridge-letter')!;
        expect(letter.querySelector('.g')!.textContent).toBe(KASRA);
        expect(letter.dataset.cellTimed).toBe('1');
        expect(letter.dataset.cellStart).toBe('0.3');
        // phoneme row: the i, lifted out of word N's inline phonemes.
        expect(bridge.querySelector('.mega-phoneme')!.textContent!.trim()).toBe('i');
        const wNblock = container.querySelectorAll<HTMLElement>('.mega-block')[0]!;
        const wNphon = Array.from(wNblock.querySelectorAll('.mega-phoneme')).map((s) => s.textContent!.trim());
        expect(wNphon).toEqual(['d', 'u', 'n']); // the i is NOT inline
        // the kasra small cell is not duplicated inside word N's letter row.
        const wNletterMarks = Array.from(wNblock.querySelectorAll('.haraka-cell .g')).map((s) => s.textContent);
        expect(wNletterMarks).not.toContain(KASRA);
    });

    it('fatḥatan+silent-alef (خَيْرًا): the silent alef stays in word N, the kasra bridges after it', () => {
        // خيرا ٱل… : tanwīn fatḥatan + a silent alef carrier, then hamza-waṣl. The
        // bridge skips the silent alef — alef greyed in word N, kasra in the bridge.
        const ivals = intervals([
            { sym: 'x', start: 0, end: 0.1 }, // 0 خ
            { sym: 'a', start: 0.1, end: 0.2 }, // 1
            { sym: 'j', start: 0.2, end: 0.3 }, // 2 ي
            { sym: 'r', start: 0.3, end: 0.4 }, // 3 ر
            { sym: 'a', start: 0.4, end: 0.45 }, // 4 fatḥatan vowel
            { sym: 'n', start: 0.45, end: 0.5 }, // 5 fatḥatan nūn
            { sym: 'i', start: 0.5, end: 0.6 }, // 6 iltiqaa kasra (lifted)
            { sym: 'l', start: 0.6, end: 0.8 }, // 7 next word lām
        ]);
        const wN = cellWord('2:1:1', [
            { char: 'خ', start: 0, end: 0.2 }, { char: 'ي', start: 0.2, end: 0.3 },
            { char: 'ر', start: 0.3, end: 0.5 }, { char: 'ا', start: 0.5, end: 0.5, silent: true },
        ], [
            { chars: 'خ', role: 'base', status: 'present', phonemeIndices: [0], sourceLetterIndex: 0, tag: null, shareGroup: null },
            { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, tag: null, shareGroup: null },
            { chars: 'ي', role: 'base', status: 'present', phonemeIndices: [2], sourceLetterIndex: 1, tag: null, shareGroup: null },
            { chars: 'ر', role: 'base', status: 'present', phonemeIndices: [3], sourceLetterIndex: 2, tag: null, shareGroup: null },
            { chars: 'ً', role: 'tanween', status: 'present', phonemeIndices: [4, 5], sourceLetterIndex: 2, tag: null, shareGroup: null },
            { chars: '', role: 'haraka', status: 'inserted', phonemeIndices: [6], sourceLetterIndex: 2, tag: 'iltiqaa_kasra', shareGroup: null },
            { chars: 'ا', role: 'base', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 3, tag: null, shareGroup: null },
        ], [0, 1, 2, 3, 4, 5, 6]);
        const wNext = cellWord('2:1:2', [
            { char: 'ٱ', start: 0.6, end: 0.6 }, { char: 'ل', start: 0.6, end: 0.8 },
        ], [
            { chars: 'ٱ', role: 'base', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 0, tag: null, shareGroup: null },
            { chars: 'ل', role: 'base', status: 'present', phonemeIndices: [7], sourceLetterIndex: 1, tag: null, shareGroup: null },
        ], [7]);
        const { container } = mount([wN, wNext], ivals);

        const wNblock = container.querySelectorAll<HTMLElement>('.mega-block')[0]!;
        // the silent alef stays in word N's letter row, greyed.
        const silentAlef = Array.from(wNblock.querySelectorAll<HTMLElement>('.mega-letter.silent'))
            .find((el) => el.textContent === 'ا');
        expect(silentAlef).toBeTruthy();
        // the kasra is in the bridge, not inside word N.
        const bridge = container.querySelector<HTMLElement>('.crossword-bridge.borderless')!;
        expect(bridge.querySelector('.bridge-letter .g')!.textContent).toBe(KASRA);
        expect(wNblock.querySelector('.bridge-letter')).toBeNull();
        // i lifted out of word N inline phonemes.
        const wNphon = Array.from(wNblock.querySelectorAll('.mega-phoneme')).map((s) => s.textContent!.trim());
        expect(wNphon).toEqual(['x', 'a', 'j', 'r', 'a', 'n']);
    });
});

describe('UnifiedDisplay — word-unit grouping (justification atoms)', () => {
    beforeEach(() => {
        dashPort.attachElement(
            makePortAudioStub({ src: 'http://audio/28.mp3', readyState: 4 }) as unknown as HTMLAudioElement,
        );
        dashPort.setSource({ audioUrl: 'http://audio/28.mp3', reciter: null, vbr: false });
    });
    afterEach(() => {
        cleanup();
        loadedVerse.set(null);
        dashPort.attachElement(null);
    });

    function timedWord(loc: string, ch: string, start: number, end: number, idx: number[]): TsWord {
        return {
            location: loc, text: ch, display_text: ch, start, end, phoneme_indices: idx,
            letters: [{ char: ch, start, end, silent: false }],
            cells: [{ chars: ch, role: 'base', status: 'present', phonemeIndices: idx, sourceLetterIndex: 0, tag: null, shareGroup: null }],
        };
    }

    it('keeps a bridge-linked pair in ONE word-unit', () => {
        // iltiqaa connecting-kasra bridges word N and N+1 → one unbreakable unit.
        const ivals = intervals([
            { sym: 'd', start: 0, end: 0.1 }, { sym: 'u', start: 0.1, end: 0.2 },
            { sym: 'n', start: 0.2, end: 0.3 }, { sym: 'i', start: 0.3, end: 0.4 },
            { sym: 'l', start: 0.4, end: 0.6 },
        ]);
        const wN = cellWord('2:1:1', [{ char: 'د', start: 0, end: 0.3 }], [
            { chars: 'د', role: 'base', status: 'present', phonemeIndices: [0], sourceLetterIndex: 0, tag: null, shareGroup: null },
            { chars: 'ٌ', role: 'tanween', status: 'present', phonemeIndices: [1, 2], sourceLetterIndex: 0, tag: null, shareGroup: null },
            { chars: '', role: 'haraka', status: 'inserted', phonemeIndices: [3], sourceLetterIndex: 0, tag: 'iltiqaa_kasra', shareGroup: null },
        ], [0, 1, 2, 3]);
        const wNext = cellWord('2:1:2', [
            { char: 'ٱ', start: 0.4, end: 0.4 }, { char: 'ل', start: 0.4, end: 0.6 },
        ], [
            { chars: 'ٱ', role: 'base', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 0, tag: null, shareGroup: null },
            { chars: 'ل', role: 'base', status: 'present', phonemeIndices: [4], sourceLetterIndex: 1, tag: null, shareGroup: null },
        ], [4]);
        const { container } = mount([wN, wNext], ivals);
        const units = container.querySelectorAll<HTMLElement>('.word-unit');
        expect(units.length).toBe(1); // the bridged pair never splits across rows
        expect(units[0]!.querySelectorAll('.mega-block').length).toBe(2);
        expect(units[0]!.querySelector('.crossword-bridge')).toBeTruthy();
    });

    it('pairs a word and the next across a pause into ONE unit with the stop cell between', () => {
        // word A (0–0.5), silence, word B (0.8–1.2): the pause connector joins A and B
        // into one unbreakable unit with the stop cell sitting BETWEEN the two words.
        const ivals = intervals([{ sym: 'a', start: 0, end: 0.5 }, { sym: 'b', start: 0.8, end: 1.2 }]);
        const { container } = mount(
            [timedWord('2:1:1', 'ا', 0, 0.5, [0]), timedWord('2:1:2', 'ب', 0.8, 1.2, [1])],
            ivals,
        );
        const units = container.querySelectorAll<HTMLElement>('.word-unit');
        expect(units.length).toBe(1); // the pause pairs its two words on one row
        expect(units[0]!.querySelectorAll('.mega-block').length).toBe(2);
        const kids = Array.from(units[0]!.children);
        expect(kids[0]!.classList.contains('mega-block')).toBe(true);
        expect(kids[1]!.classList.contains('pause-bridge')).toBe(true); // stop cell between
        expect(kids[2]!.classList.contains('mega-block')).toBe(true);
    });

    it('puts plain contiguous words in separate units', () => {
        // word A (0–0.5) then word B (0.5–1.0): contiguous (no gap, no bridge) → 2 units.
        const ivals = intervals([{ sym: 'a', start: 0, end: 0.5 }, { sym: 'b', start: 0.5, end: 1.0 }]);
        const { container } = mount(
            [timedWord('2:1:1', 'ا', 0, 0.5, [0]), timedWord('2:1:2', 'ب', 0.5, 1.0, [1])],
            ivals,
        );
        expect(container.querySelectorAll('.word-unit').length).toBe(2);
    });
});
