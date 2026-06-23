/**
 * UnifiedDisplay diacritic-cell rendering tests (schema v5, cell-group model).
 *
 * The analysis letter row is built from `word.cells` as the single ordered
 * source. GROUPING splits on `base` cells: a group = a base cell + all following
 * non-base cells until the next base. Full cells (base + real madd carrier) are
 * letter-sized; haraka / tanween render as SMALL cells pinned top/bottom and
 * light on their own phoneme interval. Sukūn cells are filtered. Iqlab tanwīn
 * fuses with a mini-meem in one cell. Implicit madd (chars==='') is a full cell
 * with an inserted/replaced affordance. Cells sharing a shareGroup co-light.
 */
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { dashPort } from '../../../../lib/playback/dash-port';
import { makeAudioStub as makePortAudioStub } from '../../../../lib/playback/__tests__/raf-harness';
import type {
    Letter,
    PhonemeInterval,
    TsCell,
    TsVerseData,
    TsWord,
} from '../../../../lib/types/ts-client';
import { loadedVerse } from '../../stores/verse';

import UnifiedDisplay from '../UnifiedDisplay.svelte';

function w(letters: Letter[], cells: TsCell[], phoneme_indices: number[]): TsWord {
    const text = letters.map((l) => l.char).join('');
    return { location: '1:2:1', text, display_text: text, start: 0, end: 1, phoneme_indices, letters, cells };
}

/** A `base` cell — the ordered anchor for a group, glyph from word.letters. */
function base(sourceLetterIndex: number, phonemeIndices: number[], extra: Partial<TsCell> = {}): TsCell {
    return {
        chars: '', role: 'base', status: 'present', phonemeIndices, sourceLetterIndex,
        tag: null, shareGroup: null, ...extra,
    };
}

function mount(words: TsWord[], intervals: PhonemeInterval[]) {
    const data: TsVerseData = {
        reciter: 'test', chapter: 1, verse_ref: '1:2', audio_url: 'http://audio/1.mp3',
        audio_category: 'by_surah_audio', time_start_ms: 0, time_end_ms: 999_999, intervals, words,
    };
    loadedVerse.set({ data, tsSegOffset: 0, tsSegEnd: 999 });
    return render(UnifiedDisplay);
}

describe('UnifiedDisplay — diacritic cells (cell-group model)', () => {
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

    it('builds adjacent cell-groups (no .mega-letter-stack) — base + pinned diacritic', () => {
        // بِسَ : ب+kasra (below), س+fatḥa (above). Two groups, each base + small cell.
        const intervals: PhonemeInterval[] = [
            { phone: 'b', start: 0, end: 0.1 }, { phone: 'i', start: 0.1, end: 0.2 },
            { phone: 's', start: 0.2, end: 0.3 }, { phone: 'a', start: 0.3, end: 0.4 },
        ];
        const word = w(
            [
                { char: 'ب', start: 0, end: 0.2, silent: false },
                { char: 'س', start: 0.2, end: 0.4, silent: false },
            ],
            [
                base(0, [0]),
                { chars: 'ِ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, tag: null, shareGroup: null },
                base(1, [2]),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [3], sourceLetterIndex: 1, tag: null, shareGroup: null },
            ],
            [0, 1, 2, 3],
        );
        const { container } = mount([word], intervals);

        // No old stack element survives.
        expect(container.querySelector('.mega-letter-stack')).toBeNull();
        expect(container.querySelector('.dia-row')).toBeNull();

        // Two groups; each is a flex child holding a base + a small cell.
        const groups = container.querySelectorAll<HTMLElement>('.cell-group');
        expect(groups.length).toBe(2);

        // The base letters are the full cells.
        const letters = container.querySelectorAll<HTMLElement>('.mega-letter:not(.implicit)');
        expect(Array.from(letters).map((l) => l.textContent)).toEqual(['ب', 'س']);

        // kasra pins bottom, fatḥa pins top.
        const kasra = container.querySelector<HTMLElement>('.haraka-cell.pin-bottom')!;
        const fatha = container.querySelector<HTMLElement>('.haraka-cell.pin-top')!;
        expect(kasra.querySelector('.g')!.textContent).toBe('ِ');
        expect(fatha.querySelector('.g')!.textContent).toBe('َ');
    });

    it('times a base on its consonant and the haraka on the vowel', () => {
        const intervals: PhonemeInterval[] = [
            { phone: 'b', start: 0, end: 0.1 }, { phone: 'i', start: 0.1, end: 0.2 },
        ];
        const word = w(
            [{ char: 'ب', start: 0, end: 0.2, silent: false }],
            [
                base(0, [0]),
                { chars: 'ِ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, tag: null, shareGroup: null },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);

        // Base full cell lights on its consonant interval [0,0.1].
        const baseCell = container.querySelector<HTMLElement>('.mega-letter[data-cell-timed]')!;
        expect(baseCell.dataset.cellStart).toBe('0');
        expect(baseCell.dataset.cellEnd).toBe('0.1');
        // It still carries the LETTER's full [start,end] for click/loop.
        expect(baseCell.dataset.letterStart).toBe('0');
        expect(baseCell.dataset.letterEnd).toBe('0.2');

        // The kasra lights on the vowel interval [0.1,0.2].
        const kasra = container.querySelector<HTMLElement>('.haraka-cell[data-cell-timed]')!;
        expect(kasra.dataset.cellStart).toBe('0.1');
        expect(kasra.dataset.cellEnd).toBe('0.2');
    });

    it('filters a sukūn cell — never rendered', () => {
        const intervals: PhonemeInterval[] = [{ phone: 'm', start: 0, end: 0.2 }];
        const word = w(
            [{ char: 'م', start: 0, end: 0.2, silent: false }],
            [
                base(0, [0]),
                { chars: 'ْ', role: 'haraka', status: 'present', phonemeIndices: [], sourceLetterIndex: 0, tag: null, shareGroup: null },
            ],
            [0],
        );
        const { container } = mount([word], intervals);
        // The base renders; the sukūn does not become a small cell.
        expect(container.querySelectorAll('.mega-letter:not(.implicit)').length).toBe(1);
        expect(container.querySelectorAll('.haraka-cell').length).toBe(0);
    });

    it('greys a dropped tanween — no timing, never lights', () => {
        const intervals: PhonemeInterval[] = [{ phone: 'm', start: 0, end: 0.2 }];
        const word = w(
            [{ char: 'م', start: 0, end: 0.2, silent: false }],
            [
                base(0, [0]),
                { chars: 'ٌ', role: 'tanween', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 0, tag: null, shareGroup: null },
            ],
            [0],
        );
        const { container } = mount([word], intervals);
        const cell = container.querySelector<HTMLElement>('.haraka-cell.dia-dropped')!;
        expect(cell).toBeTruthy();
        expect(cell.dataset.cellTimed).toBeUndefined();
    });

    it('renders iqlab as a SINGLE haraka + mini-meem (not a doubled tanwīn)', () => {
        // fatḥatan iqlab → fatḥa + mini-meem-above composed in one DK glyph; the
        // doubled tanwīn mark is NEVER shown.
        const intervals: PhonemeInterval[] = [
            { phone: 'b', start: 0, end: 0.1 }, { phone: 'm', start: 0.1, end: 0.3 },
        ];
        const word = w(
            [{ char: 'ب', start: 0, end: 0.1, silent: false }],
            [
                base(0, [0]),
                { chars: 'ً', role: 'tanween', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, tag: 'iqlab_tanween', shareGroup: null },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        const cell = container.querySelector<HTMLElement>('.haraka-cell.pin-top')!;
        expect(cell).toBeTruthy();
        const g = cell.querySelector<HTMLElement>('.g')!.textContent!;
        expect(g).toContain('َ'); // single fatḥa
        expect(g).toContain('ۢ'); // mini-meem above
        expect(g).not.toContain('ً'); // NOT the doubled tanwīn
        expect(container.querySelector('.fused')).toBeNull(); // no fusion hack
    });

    it('renders an implicit madd as a FULL cell with an inserted affordance', () => {
        // madd_iwad → an added alef, full cell, "replaced"/"inserted" glow.
        const intervals: PhonemeInterval[] = [
            { phone: 'n', start: 0, end: 0.1 }, { phone: 'a:', start: 0.1, end: 0.4 },
        ];
        const word = w(
            [{ char: 'ن', start: 0, end: 0.1, silent: false }],
            [
                base(0, [0]),
                { chars: '', role: 'madd', status: 'inserted', phonemeIndices: [1], sourceLetterIndex: 0, tag: 'madd_iwad', shareGroup: null },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        const implicit = container.querySelector<HTMLElement>('.mega-letter.implicit')!;
        expect(implicit).toBeTruthy();
        expect(implicit.textContent).toBe('ا'); // added alef
        expect(implicit.classList.contains('dia-inserted')).toBe(true);
        expect(implicit.dataset.cellTimed).toBe('1');
        expect(implicit.dataset.cellStart).toBe('0.1');
    });

    it('renders an implicit hamza-waṣl vowel as an inserted small cell with derived glyph', () => {
        const intervals: PhonemeInterval[] = [
            { phone: 'ʔ', start: 0, end: 0.1 }, { phone: 'a', start: 0.1, end: 0.2 },
        ];
        const word = w(
            [{ char: 'ٱ', start: 0, end: 0.1, silent: false }],
            [
                base(0, [0]),
                { chars: '', role: 'haraka', status: 'inserted', phonemeIndices: [1], sourceLetterIndex: 0, tag: 'hamza_wasl_vowel', shareGroup: null },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        const cell = container.querySelector<HTMLElement>('.haraka-cell.dia-inserted')!;
        expect(cell).toBeTruthy();
        expect(cell.querySelector('.g')!.textContent).toBe('َ'); // fatḥa derived from 'a'
        expect(cell.dataset.cellTimed).toBe('1');
        expect(cell.dataset.cellStart).toBe('0.1');
    });

    it('renders a real long-vowel carrier as a FULL cell (regression: dropped ا/ي)', () => {
        // مِي: م (base, consonant) + kasra (small) + ي carrier (role madd, NO base
        // cell — this is the shape that was silently dropped). The ي MUST render as
        // a full letter cell; the kasra is the only small cell.
        const intervals: PhonemeInterval[] = [
            { phone: 'm', start: 0, end: 0.1 }, { phone: 'i:', start: 0.1, end: 0.4 },
        ];
        const word = w(
            [
                { char: 'م', start: 0, end: 0.1, silent: false },
                { char: 'ي', start: 0.1, end: 0.4, silent: false },
            ],
            [
                base(0, [0]),
                { chars: 'ِ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, tag: null, shareGroup: 1 },
                { chars: 'ي', role: 'madd', status: 'present', phonemeIndices: [1], sourceLetterIndex: 1, tag: null, shareGroup: 1 },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        const letters = container.querySelectorAll<HTMLElement>('.mega-letter:not(.implicit)');
        expect(Array.from(letters).map((l) => l.textContent)).toEqual(['م', 'ي']);
        const small = container.querySelectorAll<HTMLElement>('.haraka-cell .g');
        expect(Array.from(small).map((c) => c.textContent)).toEqual(['ِ']);
    });

    it('groups a long vowel as [diacritic, carrier] with its base SEPARATED', () => {
        // مِي → base م in its OWN group; the kasra + ي carrier form a `vowel` group.
        const intervals: PhonemeInterval[] = [
            { phone: 'm', start: 0, end: 0.1 }, { phone: 'i:', start: 0.1, end: 0.4 },
        ];
        const word = w(
            [
                { char: 'م', start: 0, end: 0.1, silent: false },
                { char: 'ي', start: 0.1, end: 0.4, silent: false },
            ],
            [
                base(0, [0]),
                { chars: 'ِ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, tag: null, shareGroup: 1 },
                { chars: 'ي', role: 'madd', status: 'present', phonemeIndices: [1], sourceLetterIndex: 1, tag: null, shareGroup: 1 },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        const groups = container.querySelectorAll<HTMLElement>('.cell-group');
        expect(groups.length).toBe(2);
        // Group 0: the base م alone (no diacritic), NOT a vowel group.
        expect(groups[0]!.classList.contains('vowel')).toBe(false);
        expect(groups[0]!.querySelectorAll('.haraka-cell').length).toBe(0);
        expect(groups[0]!.querySelector('.mega-letter')!.textContent).toBe('م');
        // Group 1: the long-vowel unit — kasra (small) + ي (full), kind vowel, shared.
        expect(groups[1]!.classList.contains('vowel')).toBe(true);
        expect(groups[1]!.classList.contains('share-group')).toBe(true);
        expect(groups[1]!.querySelector('.haraka-cell .g')!.textContent).toBe('ِ');
        expect(groups[1]!.querySelector('.mega-letter')!.textContent).toBe('ي');
        // The kasra co-lights on the shared long-vowel union [0.1,0.4].
        const kasra = groups[1]!.querySelector<HTMLElement>('.haraka-cell[data-cell-timed]')!;
        expect(kasra.dataset.cellStart).toBe('0.1');
        expect(kasra.dataset.cellEnd).toBe('0.4');
    });

    it('renders a geminated base verbatim from chars (shaddah composed by the phonemizer)', () => {
        // رَبِّ: the ب is geminated — the phonemizer composes ◌ّ into the base
        // cell's chars (بّ); the FE renders chars verbatim (no phone inspection).
        const intervals: PhonemeInterval[] = [
            { phone: 'rˤ', start: 0, end: 0.1 }, { phone: 'aˤ', start: 0.1, end: 0.2 },
            { phone: 'bb', start: 0.2, end: 0.4 }, { phone: 'i', start: 0.4, end: 0.5 },
        ];
        const word = w(
            [
                { char: 'ر', start: 0, end: 0.2, silent: false },
                { char: 'ب', start: 0.2, end: 0.5, silent: false },
            ],
            [
                base(0, [0], { chars: 'ر' }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, tag: null, shareGroup: null },
                base(1, [2], { chars: 'بّ' }),
                { chars: 'ِ', role: 'haraka', status: 'present', phonemeIndices: [3], sourceLetterIndex: 1, tag: null, shareGroup: null },
            ],
            [0, 1, 2, 3],
        );
        const { container } = mount([word], intervals);
        const letters = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter:not(.implicit)'));
        expect(letters.map((l) => l.textContent)).toEqual(['ر', 'بّ']);
    });

    it('VERIFICATION: drops nothing — every non-sukūn cell renders (real ٱلْعَـٰلَمِينَ)', () => {
        // The exact word that lost its ا: dagger-alef ٰ (madd) + carrier ي (madd)
        // must both render as full cells; sukūn must not; total rendered cells ==
        // non-sukūn cell count.
        const intervals: PhonemeInterval[] = [
            { phone: 'l', start: 0, end: 0.1 }, { phone: 'ʕ', start: 0.1, end: 0.2 },
            { phone: 'a:', start: 0.2, end: 0.4 }, { phone: 'l', start: 0.4, end: 0.5 },
            { phone: 'a', start: 0.5, end: 0.6 }, { phone: 'm', start: 0.6, end: 0.7 },
            { phone: 'i:', start: 0.7, end: 0.9 }, { phone: 'n', start: 0.9, end: 1 },
        ];
        const letters: Letter[] = [
            { char: 'ٱ', start: null, end: null, silent: true },
            { char: 'ل', start: 0, end: 0.1, silent: false },
            { char: 'ع', start: 0.1, end: 0.2, silent: false },
            { char: 'ٰ', start: 0.2, end: 0.4, silent: false },
            { char: 'ل', start: 0.4, end: 0.5, silent: false },
            { char: 'م', start: 0.6, end: 0.7, silent: false },
            { char: 'ي', start: 0.7, end: 0.9, silent: false },
            { char: 'ن', start: 0.9, end: 1, silent: false },
        ];
        // Real shape (from a dev_fixture shard): base cells carry their consonant
        // char; the phonemizer's source_letter_index (dagger folded into ع) does
        // NOT match the aligner's 8 letters — which is exactly why glyphs come
        // from cell.chars, not word.letters.
        const cells: TsCell[] = [
            base(0, [], { status: 'dropped', chars: 'ٱ' }),
            base(1, [0], { chars: 'ل' }),
            { chars: 'ْ', role: 'haraka', status: 'present', phonemeIndices: [], sourceLetterIndex: 1, tag: null, shareGroup: null }, // sukūn — filtered
            base(2, [1], { chars: 'ع' }),
            { chars: 'ٰ', role: 'madd', status: 'present', phonemeIndices: [2], sourceLetterIndex: 2, tag: null, shareGroup: 0 },
            { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [2], sourceLetterIndex: 2, tag: null, shareGroup: 0 },
            base(3, [3], { chars: 'ل' }),
            { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [4], sourceLetterIndex: 3, tag: null, shareGroup: null },
            base(4, [5], { chars: 'م' }),
            { chars: 'ِ', role: 'haraka', status: 'present', phonemeIndices: [6], sourceLetterIndex: 4, tag: null, shareGroup: 1 },
            { chars: 'ي', role: 'madd', status: 'present', phonemeIndices: [6], sourceLetterIndex: 5, tag: null, shareGroup: 1 },
            base(6, [7], { chars: 'ن' }),
            { chars: 'َ', role: 'haraka', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 6, tag: null, shareGroup: null },
        ];
        const word = w(letters, cells, [0, 1, 2, 3, 4, 5, 6, 7]);
        const { container } = mount([word], intervals);

        // The dagger-alef and the ي carrier BOTH render as full cells.
        const fullText = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter')).map((l) => l.textContent);
        expect(fullText).toContain('ٰ');
        expect(fullText).toContain('ي');
        // The sukūn never renders.
        const smallGlyphs = Array.from(container.querySelectorAll<HTMLElement>('.haraka-cell .g')).map((g) => g.textContent);
        expect(smallGlyphs).not.toContain('ْ');
        // No grapheme dropped: rendered (full + small) == non-sukūn cell count.
        const nonSukun = cells.filter((c) => !(c.role === 'haraka' && c.chars === 'ْ')).length;
        const rendered =
            container.querySelectorAll('.mega-letter').length + container.querySelectorAll('.haraka-cell').length;
        expect(rendered).toBe(nonSukun);
    });

    it('renders idgham/ikhfaa tanwīn OPEN (U+08F1) but iẓhar tanwīn STACKED', () => {
        const intervals: PhonemeInterval[] = [
            { phone: 'ʕ', start: 0, end: 0.1 }, { phone: 'u', start: 0.1, end: 0.2 }, { phone: 'n', start: 0.2, end: 0.3 },
        ];
        // iẓhar (no following-assimilation tag) → STACKED canonical ḍammatan.
        const izhar = w(
            [{ char: 'ع', start: 0, end: 0.3, silent: false }],
            [base(0, [0], { chars: 'ع' }),
             { chars: 'ٌ', role: 'tanween', status: 'present', phonemeIndices: [1, 2], sourceLetterIndex: 0, tag: null, shareGroup: null }],
            [0, 1, 2],
        );
        let { container } = mount([izhar], intervals);
        expect(container.querySelector('.haraka-cell .g')!.textContent).toBe('ٌ');
        cleanup();
        // idgham (assimilates into the next word) → OPEN ḍammatan (U+08F1).
        const idgham = w(
            [{ char: 'ع', start: 0, end: 0.3, silent: false }],
            [base(0, [0], { chars: 'ع' }),
             { chars: 'ٌ', role: 'tanween', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, tag: 'idgham_ghunnah_tanween', shareGroup: null }],
            [0, 1],
        );
        ({ container } = mount([idgham], intervals));
        expect(container.querySelector('.haraka-cell .g')!.textContent).toBe(String.fromCodePoint(0x08f1));
    });

    it('madd-ʿiwaḍ: dropped tanwīn → a fatḥa grouped + co-lit with the added alef', () => {
        // ضًا at waqf: ض base, dropped fatḥatan (tag madd_iwad), added alef (replaced a:).
        const intervals: PhonemeInterval[] = [
            { phone: 'dˤ', start: 0, end: 0.2 }, { phone: 'aˤ:', start: 0.2, end: 0.6 },
        ];
        const word = w(
            [{ char: 'ض', start: 0, end: 0.2, silent: false }, { char: 'ا', start: 0.2, end: 0.6, silent: false }],
            [
                base(0, [0], { chars: 'ض' }),
                { chars: 'ً', role: 'tanween', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 0, tag: 'madd_iwad', shareGroup: null },
                { chars: 'ا', role: 'madd', status: 'replaced', phonemeIndices: [1], sourceLetterIndex: 1, tag: 'madd_iwad', shareGroup: null },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        const groups = container.querySelectorAll<HTMLElement>('.cell-group');
        // ض base separate; the iwaḍ group = [fatḥa(small), alef(full)].
        const vowel = Array.from(groups).find((g) => g.classList.contains('vowel'))!;
        expect(vowel).toBeTruthy();
        const small = vowel.querySelector<HTMLElement>('.haraka-cell .g')!;
        expect(small.textContent).toBe('َ'); // a SINGLE fatḥa, not the fatḥatan
        expect(vowel.querySelector('.mega-letter')!.textContent).toBe('ا');
        // the fatḥa co-lights on the alef's long ā (timed, not greyed).
        const fatha = vowel.querySelector<HTMLElement>('.haraka-cell')!;
        expect(fatha.dataset.cellTimed).toBe('1');
        expect(fatha.dataset.cellStart).toBe('0.2');
    });

    it('madd-ʿiwaḍ at hamza waqf: dropped fatḥatan groups + co-lights with the IMPLICIT alef', () => {
        // مَآءً at waqf ends in hamza with NO written alef carrier: ء base, dropped
        // fatḥatan (tag madd_iwad), and an INSERTED graphemeless alef (chars='', a:).
        // The fatḥa must join the implicit alef as [fatḥa, alef] and co-light, not grey.
        const intervals: PhonemeInterval[] = [
            { phone: 'ʔ', start: 0, end: 0.2 }, { phone: 'a:', start: 0.2, end: 0.6 },
        ];
        const word = w(
            [{ char: 'ء', start: 0, end: 0.2, silent: false }],
            [
                base(0, [0], { chars: 'ء' }),
                { chars: 'ً', role: 'tanween', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 0, tag: 'madd_iwad', shareGroup: null },
                { chars: '', role: 'madd', status: 'inserted', phonemeIndices: [1], sourceLetterIndex: 0, tag: 'madd_iwad', shareGroup: null },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        const groups = container.querySelectorAll<HTMLElement>('.cell-group');
        // ء base separate; the iwaḍ group = [fatḥa(small), implicit alef(full)].
        const vowel = Array.from(groups).find((g) => g.classList.contains('vowel'))!;
        expect(vowel).toBeTruthy();
        const small = vowel.querySelector<HTMLElement>('.haraka-cell .g')!;
        expect(small.textContent).toBe('َ'); // a SINGLE fatḥa, not the fatḥatan
        // the added alef is an implicit, inserted-glow full cell rendering 'ا'.
        const implicit = vowel.querySelector<HTMLElement>('.mega-letter.implicit')!;
        expect(implicit).toBeTruthy();
        expect(implicit.textContent).toBe('ا');
        expect(implicit.classList.contains('dia-inserted')).toBe(true);
        // the fatḥa co-lights on the alef's long ā (timed, not greyed).
        const fatha = vowel.querySelector<HTMLElement>('.haraka-cell')!;
        expect(fatha.dataset.cellTimed).toBe('1');
        expect(fatha.dataset.cellStart).toBe('0.2');
    });

    it('madd-ʿiwaḍ at hamza waqf works with VERSE-GLOBAL indices (iwaḍ word is 2nd)', () => {
        // Production indices are verse-global, not word-local: ...مَآءً as the 2nd
        // word, its phones offset past word 1. Proves iwadIv resolves at the global
        // index so the dropped fatḥatan still groups + co-lights with the alef.
        const intervals: PhonemeInterval[] = [
            { phone: 'w', start: 0, end: 0.1 },     // word 1: وَ
            { phone: 'a', start: 0.1, end: 0.2 },
            { phone: 'm', start: 0.2, end: 0.3 },   // word 2: مَآءً (global 2..5)
            { phone: 'a:', start: 0.3, end: 0.6 },
            { phone: 'ʔ', start: 0.6, end: 0.7 },
            { phone: 'a:', start: 0.7, end: 1.0 },  // the iwaḍ ā at global idx 5
        ];
        const wa = w(
            [{ char: 'و', start: 0, end: 0.2, silent: false }],
            [
                base(0, [0], { chars: 'و' }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, tag: null, shareGroup: null },
            ],
            [0, 1],
        );
        const maa = w(
            [
                { char: 'م', start: 0.2, end: 0.3, silent: false },
                { char: 'آ', start: 0.3, end: 0.6, silent: false },
                { char: 'ء', start: 0.6, end: 0.7, silent: false },
            ],
            [
                base(0, [2], { chars: 'م' }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [3], sourceLetterIndex: 0, tag: null, shareGroup: 9 },
                { chars: 'آ', role: 'madd', status: 'present', phonemeIndices: [3], sourceLetterIndex: 1, tag: null, shareGroup: 9 },
                base(2, [4], { chars: 'ء' }),
                { chars: 'ً', role: 'tanween', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 2, tag: 'madd_iwad', shareGroup: null },
                { chars: '', role: 'madd', status: 'inserted', phonemeIndices: [5], sourceLetterIndex: 2, tag: 'madd_iwad', shareGroup: null },
            ],
            [2, 3, 4, 5],
        );
        const { container } = mount([wa, maa], intervals);
        // Find the iwaḍ vowel group: a vowel group whose full cell is the implicit alef.
        const groups = Array.from(container.querySelectorAll<HTMLElement>('.cell-group.vowel'));
        const iwad = groups.find((g) => g.querySelector('.mega-letter.implicit'))!;
        expect(iwad).toBeTruthy();
        expect(iwad.querySelector('.mega-letter.implicit')!.textContent).toBe('ا');
        const fatha = iwad.querySelector<HTMLElement>('.haraka-cell')!;
        expect(fatha.querySelector('.g')!.textContent).toBe('َ'); // single fatḥa
        expect(fatha.dataset.cellTimed).toBe('1');
        expect(fatha.dataset.cellStart).toBe('0.7'); // co-lit on the iwaḍ ā at global idx 5
    });

    it('idgham shafawi: a merged base absorbs the vowel — its fatḥa co-lights, not greyed', () => {
        // مَّرَض receiving meem: the consonant merged cross-word, so the base sounds
        // the VOWEL ("a"). The phonemizer hands the fatḥa as `present` sharing the
        // base's vowel index + merger group — the FE co-lights it via that group,
        // with NO phone inspection.
        const intervals: PhonemeInterval[] = [{ phone: 'a', start: 0, end: 0.25 }];
        const word = w(
            [{ char: 'م', start: 0, end: 0.25, silent: false }],
            [
                base(0, [0], { chars: 'م', shareGroup: 1 }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [0], sourceLetterIndex: 0, tag: null, shareGroup: 1 },
            ],
            [0],
        );
        const { container } = mount([word], intervals);
        const fatha = container.querySelector<HTMLElement>('.haraka-cell')!;
        expect(fatha.classList.contains('dia-dropped')).toBe(false);
        expect(fatha.dataset.cellTimed).toBe('1'); // co-lit on the base's vowel
        expect(fatha.dataset.cellStart).toBe('0');
    });

    it('idgham noon cross-word: the noon base co-lights with the receiver as a NORMAL (non-greyed) cell', () => {
        // مَن يَقُول — the noon of مَن has no own phone (dropped: the merged sound is
        // on يقول's receiving yaa, which carries j̃) but shares a group (5) with it.
        // Because it co-lights, it must NOT be greyed: it renders as an ordinary cell
        // that highlights together with the yaa through j̃ — not a silent letter.
        const intervals: PhonemeInterval[] = [
            { phone: 'm', start: 0, end: 0.1 },
            { phone: 'a', start: 0.1, end: 0.2 },
            { phone: 'j̃', start: 0.2, end: 0.5 },
        ];
        const man = w(
            [{ char: 'م', start: 0, end: 0.2, silent: false }, { char: 'ن', start: 0.2, end: 0.2, silent: true }],
            [
                base(0, [0], { chars: 'م' }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, tag: null, shareGroup: null },
                base(1, [], { chars: 'ن', status: 'dropped', tag: 'idgham_ghunnah_noon', shareGroup: 5 }),
            ],
            [0, 1],
        );
        const yaqul = w(
            [{ char: 'ي', start: 0.2, end: 0.5, silent: false }],
            [base(0, [2], { chars: 'ي', shareGroup: 5 })],
            [2],
        );
        const { container } = mount([man, yaqul], intervals);
        const noon = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .find((el) => el.textContent === 'ن')!;
        expect(noon).toBeTruthy();
        expect(noon.classList.contains('silent')).toBe(false);  // NOT greyed — a normal cell
        expect(noon.dataset.cellTimed).toBe('1');                 // co-lights through the merger
        expect(noon.dataset.cellStart).toBe('0.2');               // borrows the yaa's j̃ interval
        expect(noon.dataset.cellEnd).toBe('0.5');
    });

    it('Allah: the dropped fatḥa groups + co-lights with the implicit dagger-alef', () => {
        // …للَّه: lam (geminate), implicit dagger-alef (a:), dropped fatḥa.
        const intervals: PhonemeInterval[] = [
            { phone: 'll', start: 0, end: 0.15 }, { phone: 'a:', start: 0.15, end: 0.5 },
        ];
        const word = w(
            [{ char: 'ل', start: 0, end: 0.5, silent: false }, { char: 'ه', start: 0.5, end: 0.6, silent: false }],
            [
                base(0, [0], { chars: 'ل' }),
                { chars: '', role: 'madd', status: 'inserted', phonemeIndices: [1], sourceLetterIndex: 0, tag: 'allah_dagger_alef', shareGroup: null },
                { chars: 'َ', role: 'haraka', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 0, tag: null, shareGroup: null },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        // the dagger group holds both the implicit dagger (full) and the fatḥa (small, co-lit).
        const vowel = Array.from(container.querySelectorAll<HTMLElement>('.cell-group')).find(
            (g) => g.querySelector('.mega-letter.implicit'),
        )!;
        expect(vowel).toBeTruthy();
        const fatha = vowel.querySelector<HTMLElement>('.haraka-cell')!;
        expect(fatha).toBeTruthy();
        expect(fatha.classList.contains('dia-dropped')).toBe(false);
        expect(fatha.dataset.cellTimed).toBe('1');
        expect(fatha.dataset.cellStart).toBe('0.15'); // co-lit on the dagger ā
    });

    it('renders group gaps: gap 0 within, non-zero between (margin on group)', () => {
        const intervals: PhonemeInterval[] = [
            { phone: 'b', start: 0, end: 0.1 }, { phone: 'a', start: 0.1, end: 0.2 },
            { phone: 's', start: 0.2, end: 0.3 },
        ];
        const word = w(
            [
                { char: 'ب', start: 0, end: 0.2, silent: false },
                { char: 'س', start: 0.2, end: 0.3, silent: false },
            ],
            [
                base(0, [0]),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, tag: null, shareGroup: null },
                base(1, [2]),
            ],
            [0, 1, 2],
        );
        const { container } = mount([word], intervals);
        const groups = container.querySelectorAll<HTMLElement>('.cell-group');
        expect(groups.length).toBe(2);
        // Each group is a flex child; gap is 0 within (CSS `gap: 0`); the between-
        // group gap is the margin-inline-start applied to a `.cell-group + .cell-group`.
        const first = groups[0]!;
        // first group has base + small inside it, no nested stack.
        expect(first.querySelector('.mega-letter')).toBeTruthy();
        expect(first.querySelector('.dia-track')).toBeTruthy();
    });

    it('seeks to a diacritic cell on click (cellStart × 1000)', async () => {
        // بَ : ب base, fatḥa on phoneme idx 1 (start 0.1s). Clicking the small
        // fatḥa cell seeks to 0.1s = 100ms (tsSegOffset 0), not the word start.
        const intervals: PhonemeInterval[] = [
            { phone: 'b', start: 0, end: 0.1 }, { phone: 'a', start: 0.1, end: 0.35 },
        ];
        const word = w(
            [{ char: 'ب', start: 0, end: 0.35, silent: false }],
            [
                base(0, [0]),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, tag: null, shareGroup: null },
            ],
            [0, 1],
        );
        const seekSpy = vi.spyOn(dashPort, 'seek').mockImplementation(() => {});
        const { container } = mount([word], intervals);
        const haraka = container.querySelector<HTMLElement>('.haraka-cell.dia-seekable')!;
        expect(haraka).toBeTruthy();
        await fireEvent.click(haraka);
        expect(seekSpy).toHaveBeenCalledWith(100);
        seekSpy.mockRestore();
    });

    it('raises a duration tooltip: warmup delay, rounded to 10ms, instant when warm, reset after cooldown', async () => {
        vi.useFakeTimers();
        try {
            // ب letter spans 0..0.234s (→ 230 ms); the fatḥa is phoneme idx 1,
            // 0.157..0.234s (77 ms → 80 ms).
            const intervals: PhonemeInterval[] = [
                { phone: 'b', start: 0, end: 0.157 }, { phone: 'a', start: 0.157, end: 0.234 },
            ];
            const word = w(
                [{ char: 'ب', start: 0, end: 0.234, silent: false }],
                [
                    base(0, [0]),
                    { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, tag: null, shareGroup: null },
                ],
                [0, 1],
            );
            const { container } = mount([word], intervals);
            const letter = container.querySelector<HTMLElement>('.mega-letter:not(.implicit)')!;
            const haraka = container.querySelector<HTMLElement>('.haraka-cell')!;

            // Cold hover → nothing until the 0.5s warmup elapses, then rounded.
            await fireEvent.mouseEnter(letter);
            expect(container.querySelector('.cell-tip')).toBeNull();
            await vi.advanceTimersByTimeAsync(500);
            expect(container.querySelector('.cell-tip')!.textContent).toBe('230 ms');

            // Warm: leaving then entering another cell shows near-instantly (no delay).
            await fireEvent.mouseLeave(letter);
            await fireEvent.mouseEnter(haraka);
            expect(container.querySelector('.cell-tip')!.textContent).toBe('80 ms');

            // Cooldown: 2s after the pointer leaves with no re-entry, warm decays —
            // the next hover is cold again (no tooltip until another 0.5s).
            await fireEvent.mouseLeave(haraka);
            await vi.advanceTimersByTimeAsync(2000);
            await fireEvent.mouseEnter(letter);
            expect(container.querySelector('.cell-tip')).toBeNull();
            await vi.advanceTimersByTimeAsync(500);
            expect(container.querySelector('.cell-tip')!.textContent).toBe('230 ms');
        } finally {
            vi.useRealTimers();
        }
    });

    // --- Tajweed-rule colour badges (data-tj + --tj-badge) ------------------

    it('madd: badges the carrier grapheme + its phoneme box, NOT the haraka', () => {
        const intervals: PhonemeInterval[] = [
            { phone: 'dˤ', start: 0, end: 0.1 }, { phone: 'a:', start: 0.1, end: 0.5 },
        ];
        const word = w(
            [{ char: 'ض', start: 0, end: 0.1, silent: false }, { char: 'ا', start: 0.1, end: 0.5, silent: false }],
            [
                base(0, [0], { chars: 'ض' }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, tag: null, shareGroup: 0 },
                { chars: 'ا', role: 'madd', status: 'present', phonemeIndices: [1], sourceLetterIndex: 1, tag: 'madd_wajib_muttasil', shareGroup: 0 },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        const carrier = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .find((e) => e.textContent === 'ا')!;
        expect(carrier.dataset.tj).toBe('1');
        expect(carrier.style.getPropertyValue('--tj-badge')).toContain('madd-wajib');
        // the haraka co-lights but is NOT coloured (madd = carrier grapheme only)
        const haraka = container.querySelector<HTMLElement>('.haraka-cell')!;
        expect(haraka.dataset.tj).toBeUndefined();
        // the long-vowel phoneme box is badged
        expect(container.querySelector<HTMLElement>('.mega-phoneme[data-index="1"]')!.dataset.tj).toBe('1');
    });

    it('tanwīn idgham: both letter cells badged; the phoneme badge is the single bridge tile', () => {
        const intervals: PhonemeInterval[] = [
            { phone: 'b', start: 0, end: 0.1 },
            { phone: 'i', start: 0.1, end: 0.2 },                                       // tanwīn's own vowel
            { phone: 'm̃', start: 0.2, end: 0.6, bridge: 'idgham_ghunnah_tanween' },     // merger (bridge)
        ];
        const wordN = w(
            [{ char: 'ب', start: 0, end: 0.2, silent: false }],
            [
                base(0, [0], { chars: 'ب' }),
                { chars: 'ٍ', role: 'tanween', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, tag: 'idgham_ghunnah_tanween', shareGroup: 7 },
            ],
            [0, 1],
        );
        const wordN1 = w(
            [{ char: 'م', start: 0.2, end: 0.6, silent: false }],
            [base(0, [2], { chars: 'م', shareGroup: 7 })],
            [2],
        );
        const { container } = mount([wordN, wordN1], intervals);
        // the tanwīn's bearing LETTER (ب) is badged, NOT the tanwīn diacritic itself
        const baa = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .find((e) => e.textContent === 'ب')!;
        expect(baa.dataset.tj).toBe('1');
        expect(container.querySelector<HTMLElement>('.haraka-cell')!.dataset.tj).toBeUndefined();
        const meem = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .find((e) => e.textContent === 'م')!;
        expect(meem.dataset.tj).toBe('1');                                                  // receiver, via group
        expect(container.querySelector<HTMLElement>('.crossword-bridge .mega-phoneme')!.dataset.tj).toBe('1');
        // the source tanwīn's own vowel box is NOT badged (its merger is the bridge)
        expect(container.querySelector<HTMLElement>('.mega-phoneme[data-index="1"]')!.dataset.tj).toBeUndefined();
    });

    it('ikhfaa tanwīn: the underline is on the bearing letter, not the tanwīn diacritic', () => {
        // بَعُوضَةً (ikhfāʾ): the ة base + its fathatan tanwīn. The ghunnah underline must
        // land on the ة LETTER (like every other ghunnah rule), never on the small tanwīn
        // cell — its rule is tagged on the tanwīn but rendered on the bearing letter.
        const intervals: PhonemeInterval[] = [
            { phone: 'dˤ', start: 0, end: 0.1 }, { phone: 'a', start: 0.1, end: 0.2 },
            { phone: 't', start: 0.2, end: 0.3 }, { phone: 'a', start: 0.3, end: 0.34 },
            { phone: 'ŋ', start: 0.34, end: 0.8 },
        ];
        const word = w(
            [{ char: 'ض', start: 0, end: 0.2, silent: false }, { char: 'ة', start: 0.2, end: 0.34, silent: false }],
            [
                base(0, [0], { chars: 'ض' }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, tag: null, shareGroup: null },
                base(1, [2], { chars: 'ة' }),
                { chars: 'ً', role: 'tanween', status: 'present', phonemeIndices: [3, 4], sourceLetterIndex: 1, tag: 'ikhfaa_tanween', shareGroup: null },
            ],
            [0, 1, 2, 3, 4],
        );
        const { container } = mount([word], intervals);
        const taa = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .find((e) => e.textContent === 'ة')!;
        expect(taa.dataset.tj).toBe('1');
        expect(taa.style.getPropertyValue('--tj-badge')).toContain('ikhfaa');
        // no diacritic small cell is badged
        expect(Array.from(container.querySelectorAll<HTMLElement>('.haraka-cell'))
            .every((c) => c.dataset.tj === undefined)).toBe(true);
    });

    it('idgham shafawi: both mīms badged + the single bridge tile', () => {
        const intervals: PhonemeInterval[] = [
            { phone: 'h', start: 0, end: 0.1 },
            { phone: 'm̃', start: 0.1, end: 0.5, bridge: 'idgham_shafawi' }, // source-mīm merger (bridge)
            { phone: 'a', start: 0.5, end: 0.6 },                           // receiver mīm's vowel
        ];
        const wordN = w(
            [{ char: 'ه', start: 0, end: 0.1, silent: false }, { char: 'م', start: 0.1, end: 0.5, silent: false }],
            [base(0, [0], { chars: 'ه' }), base(1, [1], { chars: 'م', tag: 'idgham_shafawi', shareGroup: 8 })],
            [0, 1],
        );
        const wordN1 = w(
            [{ char: 'م', start: 0.5, end: 0.6, silent: false }],
            [base(0, [2], { chars: 'م', shareGroup: 8 })],
            [2],
        );
        const { container } = mount([wordN, wordN1], intervals);
        const meems = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .filter((e) => e.textContent === 'م');
        expect(meems.length).toBe(2);
        expect(meems.every((m) => m.dataset.tj === '1')).toBe(true);
        const bridge = container.querySelector<HTMLElement>('.crossword-bridge .mega-phoneme')!;
        expect(bridge.dataset.tj).toBe('1');
        expect(bridge.style.getPropertyValue('--tj-badge')).toContain('idgham-shafawi');
    });

    it('Allah dagger: arid-badged at waqf (carrier only, not the fatḥa); uncoloured continuing', () => {
        const intervals: PhonemeInterval[] = [
            { phone: 'll', start: 0, end: 0.15 }, { phone: 'a:', start: 0.15, end: 0.5 },
        ];
        const mk = (tag: string) => w(
            [{ char: 'ل', start: 0, end: 0.5, silent: false }, { char: 'ه', start: 0.5, end: 0.6, silent: false }],
            [
                base(0, [0], { chars: 'ل' }),
                { chars: '', role: 'madd', status: 'inserted', phonemeIndices: [1], sourceLetterIndex: 0, tag, shareGroup: null },
                { chars: 'َ', role: 'haraka', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 0, tag: null, shareGroup: null },
            ],
            [0, 1],
        );
        // continuing → allah_dagger_alef → no badge
        let c = mount([mk('allah_dagger_alef')], intervals).container;
        expect(c.querySelector<HTMLElement>('.mega-letter.implicit')!.dataset.tj).toBeUndefined();
        cleanup();
        // stopping → madd_arid_lissukun → dagger badged, fatḥa not
        c = mount([mk('madd_arid_lissukun')], intervals).container;
        const dagger = c.querySelector<HTMLElement>('.mega-letter.implicit')!;
        expect(dagger.dataset.tj).toBe('1');
        expect(dagger.style.getPropertyValue('--tj-badge')).toContain('madd-arid');
        // the dropped fatḥa STILL groups + co-lights with the arid dagger (it must NOT
        // fall back to the lām's base group greyed — daggerBySrc keys off the implicit
        // madd, not the allah_dagger_alef tag, so the arid waqf case still co-lights).
        const vowel = Array.from(c.querySelectorAll<HTMLElement>('.cell-group')).find(
            (g) => g.querySelector('.mega-letter.implicit'),
        )!;
        const fatha = vowel.querySelector<HTMLElement>('.haraka-cell')!;
        expect(fatha).toBeTruthy();
        expect(fatha.classList.contains('dia-dropped')).toBe(false); // co-lit, not greyed
        expect(fatha.dataset.cellTimed).toBe('1');
        expect(fatha.dataset.cellStart).toBe('0.15'); // the dagger's ā interval
        expect(fatha.dataset.tj).toBeUndefined(); // colour is carrier-only
    });

    it('no badge for ṭabīʿī madd, nor for bila-ghunnah idgham + its receiver', () => {
        const tabiiIv: PhonemeInterval[] = [
            { phone: 'q', start: 0, end: 0.1 }, { phone: 'a:', start: 0.1, end: 0.4 },
        ];
        const tabii = w(
            [{ char: 'ق', start: 0, end: 0.1, silent: false }, { char: 'ا', start: 0.1, end: 0.4, silent: false }],
            [
                base(0, [0], { chars: 'ق' }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, tag: null, shareGroup: 0 },
                { chars: 'ا', role: 'madd', status: 'present', phonemeIndices: [1], sourceLetterIndex: 1, tag: null, shareGroup: 0 },
            ],
            [0, 1],
        );
        expect(mount([tabii], tabiiIv).container.querySelector('[data-tj]')).toBeNull();
        cleanup();

        const bilaIv: PhonemeInterval[] = [
            { phone: 'b', start: 0, end: 0.1 }, { phone: 'i', start: 0.1, end: 0.2 },
            { phone: 'rˤrˤ', start: 0.2, end: 0.5, bridge: 'idgham_bila_ghunnah_tanween' },
        ];
        const bN = w(
            [{ char: 'ب', start: 0, end: 0.2, silent: false }],
            [
                base(0, [0], { chars: 'ب' }),
                { chars: 'ٍ', role: 'tanween', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, tag: 'idgham_bila_ghunnah_tanween', shareGroup: 7 },
            ],
            [0, 1],
        );
        const bN1 = w(
            [{ char: 'ر', start: 0.2, end: 0.5, silent: false }],
            [base(0, [2], { chars: 'ر', shareGroup: 7 })],
            [2],
        );
        expect(mount([bN, bN1], bilaIv).container.querySelector('[data-tj]')).toBeNull();
    });

    it('iltiqaa: the shortened carrier (no phones) greys like any silent letter', () => {
        // ٱهْدِنَا ٱللَّه — the long ā of نَا is shortened (iltiqāʾ): its alef carrier
        // sounds nothing (status=shortened, no phoneme indices). It must grey via the
        // SAME .silent path as a dropped silent letter — silence keys on "no own
        // phones + no share group", NOT on status==='dropped' (the bg-mismatch root cause).
        const intervals: PhonemeInterval[] = [
            { phone: 'n', start: 0, end: 0.1 }, { phone: 'a', start: 0.1, end: 0.2 },
        ];
        const word = w(
            [{ char: 'ن', start: 0, end: 0.1, silent: false }, { char: 'ا', start: 0.1, end: 0.2, silent: false }],
            [
                base(0, [0], { chars: 'ن' }),
                { chars: 'َ', role: 'haraka', status: 'shortened', phonemeIndices: [1], sourceLetterIndex: 0, tag: 'iltiqaa', shareGroup: null },
                { chars: 'ا', role: 'madd', status: 'shortened', phonemeIndices: [], sourceLetterIndex: 1, tag: 'iltiqaa', shareGroup: null },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        const alef = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .find((e) => e.textContent === 'ا')!;
        expect(alef).toBeTruthy();
        expect(alef.classList.contains('silent')).toBe(true);
    });
});
