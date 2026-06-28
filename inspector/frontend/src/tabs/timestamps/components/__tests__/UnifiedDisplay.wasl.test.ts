/**
 * UnifiedDisplay cross-verse waṣl context-merge tests.
 *
 * When the focused verse is part of a waṣl group, `focusWaslGroup.data` (the
 * merged group) drives the render: every member verse's words show, the
 * non-focus verses dimmed + non-loopable as context, and the cross-verse
 * junction idgham renders as a bridge tile at the boundary (the boundary words
 * are adjacent in the merged words array, so `buildRendered` lifts it for free).
 */
import { cleanup, render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { Letter, PhonemeInterval, TsVerseData, TsWord } from '../../../../lib/types/ts-client';
import { focusWaslGroup, loadedVerse } from '../../stores/verse';

import UnifiedDisplay from '../UnifiedDisplay.svelte';

function word(location: string, idxs: number[], letters: string, start: number, end: number): TsWord {
    const ls: Letter[] = [...letters].map((c) => ({ char: c, start: null, end: null }));
    return { location, text: letters, display_text: letters, start, end, phoneme_indices: idxs, letters: ls };
}

function ph(sym: string, start: number, end: number, bridge?: string): PhonemeInterval {
    return { phone: sym, start, end, ...(bridge ? { bridge } : {}) };
}

/** Merged 2-verse group: 1:1 (focus, words 1-2) waṣl»1:2 (context, word 1). The
 *  tail phone of 1:1:2 carries the junction idgham → bridges into 1:2:1. */
function groupData(): TsVerseData {
    return {
        reciter: 'r', chapter: 1, verse_ref: '1:1',
        audio_url: 'http://a/1.mp3', audio_category: 'by_surah_audio',
        time_start_ms: 0, time_end_ms: 3000,
        intervals: [
            ph('a', 0, 1),
            ph('b', 1, 1.8),
            ph('n', 1.8, 2, 'idghaam'), // junction merger
            ph('c', 2, 3),
        ],
        words: [
            word('1:1:1', [0], 'ا', 0, 1),
            word('1:1:2', [1, 2], 'بن', 1, 2),
            word('1:2:1', [3], 'ج', 2, 3),
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

    it('renders the junction idgham as a bridge tile across the boundary', () => {
        const { container } = mountGroup();
        expect(container.querySelector('.crossword-bridge')).not.toBeNull();
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
