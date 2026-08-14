/**
 * UnifiedDisplay cross-verse waṣl context-merge tests.
 *
 * When the focused verse is part of a waṣl group, `focusWaslGroup.data` (the
 * merged group) drives the render: every member verse's words show, the
 * non-focus verses dimmed + non-loopable as context.
 *
 * Junction idgham: the offline tagger phonemizes each verse-segment alone, so a
 * cross-verse merger phone carries NO `bridge` tag (unlike within-verse
 * mergers). What the shard DOES carry is the SOURCE cell tag on the last word's
 * trailing tanwīn / noon / meem. In a merged group the boundary words are
 * adjacent, so `buildRendered` synthesizes the junction bridge from that source
 * tag — lifting the next verse's nasalized head phone into the gold tile. These
 * fixtures mirror the real shard shape (source cell tagged, junction phone
 * untagged), so they pin the synthesis, not the within-verse path.
 */
import { cleanup, render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { Letter, PhonemeInterval, TsCell, TsVerseData, TsWord } from '../../../../lib/types/ts-client';
import { focusWaslGroup, loadedVerse } from '../../stores/verse';

import UnifiedDisplay from '../UnifiedDisplay.svelte';

function word(
    location: string, idxs: number[], letters: string, start: number, end: number, cells?: TsCell[],
): TsWord {
    const ls: Letter[] = [...letters].map((c) => ({ char: c, start: null, end: null }));
    return { location, text: letters, display_text: letters, start, end, phoneme_indices: idxs, letters: ls, cells };
}

function cell(over: Partial<TsCell>): TsCell {
    return { chars: '', role: 'base', status: 'present', phonemeIndices: [], sourceLetterIndex: 0, rules: [], shareGroup: null, ...over };
}

function ph(sym: string, start: number, end: number, bridge?: string): PhonemeInterval {
    return { phone: sym, start, end, ...(bridge ? { bridge } : {}) };
}

/** Merged 2-verse group: 1:1 (focus, words 1-2) waṣl»1:2 (context, word 1).
 *  1:1:2 ends in a tanwīn whose cell carries the idgham SOURCE tag (no phone
 *  bridge — the real cross-verse shape); the merger is realized as the nasalized
 *  head phone `w̃` of 1:2:1, which the synthesis lifts into the junction tile. */
function groupData(): TsVerseData {
    return {
        reciter: 'r', chapter: 1, verse_ref: '1:1',
        audio_url: 'http://a/1.mp3', audio_category: 'by_surah_audio',
        time_start_ms: 0, time_end_ms: 3000,
        intervals: [
            ph('a', 0, 1), // 0  1:1:1
            ph('b', 1, 1.6), // 1  1:1:2 base
            ph('i', 1.6, 2), // 2  1:1:2 tanwīn leftover vowel (source's own phone)
            ph('w̃', 2, 2.4), // 3  1:2:1 nasalized merger head (NO bridge tag)
            ph('c', 2.4, 3), // 4  1:2:1 rest
        ],
        words: [
            word('1:1:1', [0], 'ا', 0, 1, [cell({ chars: 'ا', phonemeIndices: [0] })]),
            word('1:1:2', [1, 2], 'بٍ', 1, 2, [
                cell({ chars: 'ب', phonemeIndices: [1] }),
                cell({ chars: 'ٍ', role: 'tanween', phonemeIndices: [2], rules: ['idgham_bi_ghunnah'], shareGroup: 0 }),
            ]),
            word('1:2:1', [3, 4], 'وج', 2, 3, [
                cell({ chars: 'و', phonemeIndices: [3] }),
                cell({ chars: 'ج', phonemeIndices: [4], sourceLetterIndex: 1 }),
            ]),
        ],
    };
}

function mountGroup() {
    const data = groupData();
    // loadedVerse stays the FOCUS occasion (here the same anchor); the merged
    // group overlay drives the render.
    loadedVerse.set({ data, tsSegOffset: 0, tsSegEnd: 2 });
    focusWaslGroup.set({ data, span: [0, 3000], refs: ['1:1', '1:2'], focusRef: '1:1' });
    return render(UnifiedDisplay);
}

describe('UnifiedDisplay — waṣl context merge', () => {
    beforeEach(() => {
        loadedVerse.set(null);
        focusWaslGroup.set(null);
    });
    afterEach(() => {
        cleanup();
        loadedVerse.set(null);
        focusWaslGroup.set(null);
    });

    it('renders every member verse with non-focus verses as context', () => {
        const { container } = mountGroup();
        const blocks = container.querySelectorAll<HTMLElement>('.mega-block');
        expect(blocks.length).toBe(3); // 1:1:1, 1:1:2, 1:2:1
        // Focus verse (1:1) blocks are interactive; the context verse (1:2) is dimmed.
        expect(blocks[0]!.classList.contains('context')).toBe(false);
        expect(blocks[1]!.classList.contains('context')).toBe(false);
        expect(blocks[2]!.classList.contains('context')).toBe(true);
    });

    it('synthesizes the junction idgham tile from the source cell tag (untagged merger phone)', () => {
        const { container } = mountGroup();
        const bridge = container.querySelector<HTMLElement>('.crossword-bridge');
        expect(bridge).not.toBeNull();
        // the lifted tile shows the nasalized merger head phone `w̃`.
        expect(bridge!.querySelector('.mega-phoneme')!.textContent!.trim()).toBe('w̃');
        // the merger is lifted OUT of 1:2:1's inline phonemes (shows once, in the tile).
        const blocks = container.querySelectorAll<HTMLElement>('.mega-block');
        const recvPhon = Array.from(blocks[2]!.querySelectorAll('.mega-phoneme')).map((s) => s.textContent!.trim());
        expect(recvPhon).toEqual(['c']);
        // bridge-joined pair stays in one unbreakable unit.
        const bridgedUnit = Array.from(container.querySelectorAll<HTMLElement>('.word-unit'))
            .find((u) => u.querySelector('.crossword-bridge'));
        expect(bridgedUnit!.querySelectorAll('.mega-block').length).toBe(2);
    });

    it('renders no junction tile when the boundary source carries no idgham tag', () => {
        // Same group shape, but 1:1:2's trailing cell is a plain consonant (no
        // bridge tag) — a non-idgham waṣl continuation must NOT fabricate a tile.
        const data = groupData();
        data.words[1]!.cells![1] = cell({ chars: 'ب', phonemeIndices: [2] });
        loadedVerse.set({ data, tsSegOffset: 0, tsSegEnd: 2 });
        focusWaslGroup.set({ data, span: [0, 3000], refs: ['1:1', '1:2'], focusRef: '1:1' });
        const { container } = render(UnifiedDisplay);
        expect(container.querySelector('.crossword-bridge')).toBeNull();
        // and the merger head phone stays inline on 1:2:1 (nothing lifted).
        const blocks = container.querySelectorAll<HTMLElement>('.mega-block');
        const recvPhon = Array.from(blocks[2]!.querySelectorAll('.mega-phoneme')).map((s) => s.textContent!.trim());
        expect(recvPhon).toEqual(['w̃', 'c']);
    });

    it('tags no context when not in a group (single-verse focus)', () => {
        const data: TsVerseData = {
            reciter: 'r', chapter: 1, verse_ref: '1:1',
            audio_url: 'http://a/1.mp3', audio_category: 'by_surah_audio',
            time_start_ms: 0, time_end_ms: 2000,
            intervals: [ph('a', 0, 1), ph('b', 1, 2)],
            words: [word('1:1:1', [0], 'ا', 0, 1), word('1:1:2', [1], 'ب', 1, 2)],
        };
        loadedVerse.set({ data, tsSegOffset: 0, tsSegEnd: 2 });
        focusWaslGroup.set(null);
        const { container } = render(UnifiedDisplay);
        const blocks = container.querySelectorAll<HTMLElement>('.mega-block');
        expect(blocks.length).toBe(2);
        expect([...blocks].every((b) => !b.classList.contains('context'))).toBe(true);
    });
});
