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
import { resetAllTajweed, setRuleEnabled } from '../../stores/tajweed-settings';
import { loadedVerse } from '../../stores/verse';
import { TS_CLICK_DELAY_MS } from '../../utils/constants';

import UnifiedDisplay from '../UnifiedDisplay.svelte';

function w(letters: Letter[], cells: TsCell[], phoneme_indices: number[]): TsWord {
    const text = letters.map((l) => l.char).join('');
    return { location: '1:2:1', text, display_text: text, start: 0, end: 1, phoneme_indices, letters, cells };
}

/** A `base` cell — the ordered anchor for a group, glyph from word.letters. */
function base(sourceLetterIndex: number, phonemeIndices: number[], extra: Partial<TsCell> = {}): TsCell {
    return {
        chars: '', role: 'base', status: 'present', phonemeIndices, sourceLetterIndex,
        rules: [], shareGroup: null, ...extra,
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

/** True when any rendered cell carries a tajweed underline (an inline box-shadow). */
function anyBadge(container: HTMLElement): boolean {
    return Array.from(
        container.querySelectorAll<HTMLElement>('.mega-letter,.mega-phoneme,.haraka-cell,.bridge-letter'),
    ).some((e) => e.style.boxShadow !== '');
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
        resetAllTajweed(); // izhar / madd-ṭabīʿī default off — undo any per-test enable
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
                { chars: 'ِ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
                base(1, [2]),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [3], sourceLetterIndex: 1, rules: [], shareGroup: null },
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
                { chars: 'ِ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
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
                { chars: 'ْ', role: 'haraka', status: 'present', phonemeIndices: [], sourceLetterIndex: 0, rules: [], shareGroup: null },
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
                { chars: 'ٌ', role: 'tanween', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 0, rules: [], shareGroup: null },
            ],
            [0],
        );
        const { container } = mount([word], intervals);
        const cell = container.querySelector<HTMLElement>('.haraka-cell.dia-dropped')!;
        expect(cell).toBeTruthy();
        expect(cell.dataset.cellTimed).toBeUndefined();
    });

    it('renders iqlab as TWO cells — a normal haraka + a standalone mini-meem', () => {
        // fatḥatan iqlab → ONE shard cell sounding [vowel, nasal]. The FE splits it
        // into the single haraka the mushaf writes and a mini-meem carrying the nasal
        // + the iqlab rule. The meem DISPLAYS the low-meem glyph but, with a ḍamma/
        // fatḥa source, pins to the TOP slot. Both anchor to ب → one group.
        const intervals: PhonemeInterval[] = [
            { phone: 'b', start: 0, end: 0.1 },
            { phone: 'a', start: 0.1, end: 0.2 },   // the haraka's vowel
            { phone: 'm', start: 0.2, end: 0.5 },   // the iqlab nasal (mini-meem)
        ];
        const word = w(
            [{ char: 'ب', start: 0, end: 0.1, silent: false }],
            [
                base(0, [0], { chars: 'ب' }),
                { chars: 'ً', role: 'tanween', status: 'present', phonemeIndices: [1, 2], sourceLetterIndex: 0, rules: ['iqlab'], shareGroup: null },
            ],
            [0, 1, 2],
        );
        const { container } = mount([word], intervals);
        // ONE group holding the base + BOTH small cells.
        const groups = container.querySelectorAll<HTMLElement>('.cell-group');
        expect(groups.length).toBe(1);
        const smalls = Array.from(container.querySelectorAll<HTMLElement>('.haraka-cell .g'));
        expect(smalls.map((g) => g.textContent)).toEqual(['َ', 'ۭ']); // haraka THEN mini-meem (below form)
        // No fused single glyph — the haraka cell shows ONLY the fatḥa.
        const haraka = smalls[0]!;
        expect(haraka.textContent).toBe('َ');
        expect(haraka.textContent).not.toContain('ۭ');
        // The mini-meem is its OWN cell (second small): the low-meem GLYPH is shown,
        // but a ḍamma/fatḥa-source (MEEM_HI) iqlab pins it to the TOP slot.
        expect(smalls[1]!.textContent).toBe('ۭ');
        const meemCell = Array.from(container.querySelectorAll<HTMLElement>('.haraka-cell'))
            .find((c) => c.querySelector('.g')!.textContent === 'ۭ')!;
        expect(meemCell.classList.contains('pin-top')).toBe(true);
        expect(container.querySelector('.fused')).toBeNull();
    });

    it('iqlab kasra: the mini-meem-below pins to the bottom slot', () => {
        // kasratan iqlab → the split haraka is a kasra (pins bottom) and the mini-meem
        // is the BELOW form (U+06ED), which also pins bottom.
        const intervals: PhonemeInterval[] = [
            { phone: 'b', start: 0, end: 0.1 },
            { phone: 'i', start: 0.1, end: 0.2 },
            { phone: 'm', start: 0.2, end: 0.5 },
        ];
        const word = w(
            [{ char: 'ب', start: 0, end: 0.1, silent: false }],
            [
                base(0, [0], { chars: 'ب' }),
                { chars: 'ٍ', role: 'tanween', status: 'present', phonemeIndices: [1, 2], sourceLetterIndex: 0, rules: ['iqlab'], shareGroup: null },
            ],
            [0, 1, 2],
        );
        const { container } = mount([word], intervals);
        const smalls = Array.from(container.querySelectorAll<HTMLElement>('.haraka-cell .g'));
        expect(smalls.map((g) => g.textContent)).toEqual(['ِ', 'ۭ']); // kasra THEN the below-meem
        const meem = Array.from(container.querySelectorAll<HTMLElement>('.haraka-cell'))
            .find((c) => c.querySelector('.g')!.textContent === 'ۭ')!;
        expect(meem).toBeTruthy();
        expect(meem.classList.contains('pin-bottom')).toBe(true);
    });

    it('iqlab: the vowel under the haraka is uncoloured; the nasal under the mini-meem is iqlab-coloured', () => {
        // The iqlab rule rides ONLY the mini-meem cell (the nasal). The haraka cell
        // (vowel) is uncoloured; the mini-meem cell + its nasal phoneme carry --tj-iqlab.
        const intervals: PhonemeInterval[] = [
            { phone: 'b', start: 0, end: 0.1 },
            { phone: 'a', start: 0.1, end: 0.2 },   // vowel (haraka)
            { phone: 'm', start: 0.2, end: 0.5 },   // nasal (mini-meem)
        ];
        const word = w(
            [{ char: 'ب', start: 0, end: 0.1, silent: false }],
            [
                base(0, [0], { chars: 'ب' }),
                { chars: 'ً', role: 'tanween', status: 'present', phonemeIndices: [1, 2], sourceLetterIndex: 0, rules: ['iqlab'], shareGroup: null },
            ],
            [0, 1, 2],
        );
        const { container } = mount([word], intervals);
        const haraka = Array.from(container.querySelectorAll<HTMLElement>('.haraka-cell'))
            .find((c) => c.querySelector('.g')!.textContent === 'َ')!;
        const meem = Array.from(container.querySelectorAll<HTMLElement>('.haraka-cell'))
            .find((c) => c.querySelector('.g')!.textContent === 'ۭ')!; // above-form input renders below
        // haraka (vowel) uncoloured
        expect(haraka.style.boxShadow).toBe('');
        // mini-meem cell coloured iqlab
        expect(meem.style.boxShadow).not.toBe('');
        expect(meem.style.boxShadow).toContain('iqlab');
        // the vowel phoneme (idx 1) is NOT coloured; the nasal phoneme (idx 2) IS.
        expect(container.querySelector<HTMLElement>('.mega-phoneme[data-index="1"]')!.style.boxShadow).toBe('');
        const nasal = container.querySelector<HTMLElement>('.mega-phoneme[data-index="2"]')!;
        expect(nasal.style.boxShadow).not.toBe('');
        expect(nasal.style.boxShadow).toContain('iqlab');
    });

    it('iqlab noon: the ن falls silent, a synthesized mini-meem owns the nasal + the lone iqlab underline', () => {
        // مِن before ب: the shard ships no mini-meem cell, so the FE synthesizes one for
        // the converted noon too. The ن renders silent + uncoloured; the
        // mini-meem (low-meem glyph, pinned top) owns the nasal phone (the click/loop
        // target) and carries the ONLY iqlab underline.
        const intervals: PhonemeInterval[] = [
            { phone: 'm', start: 0, end: 0.1 },
            { phone: 'i', start: 0.1, end: 0.2 },
            { phone: 'm', start: 0.2, end: 0.5 }, // the iqlab nasal — was the ن's phone
        ];
        const word = w(
            [
                { char: 'م', start: 0, end: 0.1, silent: false },
                { char: 'ن', start: 0.2, end: 0.5, silent: false },
            ],
            [
                base(0, [0], { chars: 'م' }),
                { chars: 'ِ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
                base(1, [2], { chars: 'ن', rules: ['iqlab'] }),
            ],
            [0, 1, 2],
        );
        const { container } = mount([word], intervals);
        // The ن renders as a silent letter with NO underline (the tag moved to the meem).
        const noon = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .find((l) => l.textContent === 'ن')!;
        expect(noon).toBeTruthy();
        expect(noon.classList.contains('silent')).toBe(true);
        expect(noon.style.boxShadow).toBe('');
        // ...but still NAMES "Iqlab" on hover (a silent-only rule, no badge).
        expect(noon.dataset.tjRules).toBe('Iqlab');
        // The synthesized mini-meem (low-meem glyph, pinned top) carries the iqlab underline...
        const meem = Array.from(container.querySelectorAll<HTMLElement>('.haraka-cell'))
            .find((c) => c.querySelector('.g')!.textContent === 'ۭ')!;
        expect(meem).toBeTruthy();
        expect(meem.classList.contains('pin-top')).toBe(true);
        expect(meem.style.boxShadow).not.toBe('');
        expect(meem.style.boxShadow).toContain('iqlab');
        // ...and owns the nasal timing (the click/loop target), not the ن.
        expect(meem.dataset.cellTimed).toBe('1');
        expect(meem.dataset.cellStart).toBe('0.2');
        expect(meem.dataset.diaLoopIdx).toBe('2');
        // The nasal phoneme (idx 2) is iqlab-coloured + aligns under the meem.
        expect(container.querySelector<HTMLElement>('.mega-phoneme[data-index="2"]')!.style.boxShadow).not.toBe('');
    });

    it('renders an inserted madd as a FULL cell with an inserted affordance', () => {
        // madd_iwad → the fatḥatan shown as a fatḥa, plus the alef a stop adds.
        const intervals: PhonemeInterval[] = [
            { phone: 'n', start: 0, end: 0.1 }, { phone: 'a:', start: 0.1, end: 0.4 },
        ];
        const word = w(
            [{ char: 'ن', start: 0, end: 0.1, silent: false }],
            [
                base(0, [0]),
                { chars: 'َ', role: 'haraka', status: 'replaced', phonemeIndices: [1], sourceLetterIndex: 0, rules: ['madd_iwad', 'madd_tabii'], shareGroup: null },
                { chars: 'ا', role: 'madd', status: 'inserted', phonemeIndices: [1], sourceLetterIndex: 0, rules: ['madd_iwad', 'madd_tabii'], shareGroup: null },
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

    it('renders the hamza-waṣl vowel a reader starting on the word says', () => {
        const intervals: PhonemeInterval[] = [
            { phone: 'ʔ', start: 0, end: 0.1 }, { phone: 'a', start: 0.1, end: 0.2 },
        ];
        const word = w(
            [{ char: 'ٱ', start: 0, end: 0.1, silent: false }],
            [
                base(0, [0]),
                { chars: 'َ', role: 'haraka', status: 'inserted', phonemeIndices: [1], sourceLetterIndex: 0, rules: ['hamza_wasl_kasra'], shareGroup: null },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        const cell = container.querySelector<HTMLElement>('.haraka-cell.dia-inserted')!;
        expect(cell).toBeTruthy();
        expect(cell.querySelector('.g')!.textContent).toBe('َ'); // the producer's own fatḥa
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
                { chars: 'ِ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: 1 },
                { chars: 'ي', role: 'madd', status: 'present', phonemeIndices: [1], sourceLetterIndex: 1, rules: [], shareGroup: 1 },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        const letters = container.querySelectorAll<HTMLElement>('.mega-letter:not(.implicit)');
        expect(Array.from(letters).map((l) => l.textContent)).toEqual(['م', 'ي']);
        const small = container.querySelectorAll<HTMLElement>('.haraka-cell .g');
        expect(Array.from(small).map((c) => c.textContent)).toEqual(['ِ']);
    });

    it('dropped ṣilah at waqf: ḍamma + mini-waw form ONE silent vowel group, ḍamma leading', () => {
        // لَهُۥ stopped ("lah"): the ṣilah drops, so the haa's ḍamma AND the mini-waw
        // are both silent. They must render as one [ḍamma, mini-waw] vowel group (ḍamma
        // first, orthographic هُ + ۥ) — NOT the ḍamma glued onto the haa base.
        const intervals: PhonemeInterval[] = [
            { phone: 'l', start: 0, end: 0.1 },
            { phone: 'a', start: 0.1, end: 0.2 },
            { phone: 'h', start: 0.2, end: 0.3 },
        ];
        const word = w(
            [
                { char: 'ل', start: 0, end: 0.2, silent: false },
                { char: 'ه', start: 0.2, end: 0.3, silent: false },
            ],
            [
                base(0, [0], { chars: 'ل' }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
                base(1, [2], { chars: 'ه' }),
                { chars: 'ُ', role: 'haraka', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 1, rules: [], shareGroup: null },
                { chars: 'ۥ', role: 'madd', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 1, rules: [], shareGroup: null },
            ],
            [0, 1, 2],
        );
        const { container } = mount([word], intervals);
        // The haa base group carries NO haraka — the ḍamma left it for the vowel group.
        const haaGroup = Array.from(container.querySelectorAll<HTMLElement>('.cell-group'))
            .find((g) => !g.classList.contains('vowel') && g.querySelector('.mega-letter')?.textContent === 'ه')!;
        expect(haaGroup).toBeTruthy();
        expect(haaGroup.querySelectorAll('.haraka-cell').length).toBe(0);
        // The ṣilah vowel group holds BOTH the ḍamma and the mini-waw, ḍamma FIRST.
        const vowel = Array.from(container.querySelectorAll<HTMLElement>('.cell-group'))
            .find((g) => g.querySelector('.mega-letter')?.textContent === 'ۥ')!;
        expect(vowel).toBeTruthy();
        expect(vowel.classList.contains('vowel')).toBe(true);
        expect(vowel.querySelector('.haraka-cell .g')!.textContent).toBe('ُ');
        const graphemes = Array.from(vowel.querySelectorAll<HTMLElement>('.haraka-cell, .mega-letter'));
        expect(graphemes[0]!.classList.contains('haraka-cell')).toBe(true); // ḍamma leads
        expect(graphemes[1]!.textContent).toBe('ۥ');                         // mini-waw after
        // Both are silent (the ṣilah dropped at the stop).
        expect(vowel.querySelector('.haraka-cell')!.classList.contains('dia-dropped')).toBe(true);
    });

    it('silah madd: the maddah cell folds onto the mini-waw carrier, not the bearing letter', () => {
        // هُۥٓ (a silah with madd, e.g. حَسْبُهُۥٓ): the producer writes the maddah as its
        // OWN cell after the ṣilah carrier. It rides the letter before it, so the haa
        // renders CLEAN (ه) and the mini-waw wears the maddah (ۥٓ).
        const MADDAH = 'ٓ';
        const intervals: PhonemeInterval[] = [
            { phone: 'l', start: 0, end: 0.1 },
            { phone: 'a', start: 0.1, end: 0.2 },
            { phone: 'h', start: 0.2, end: 0.3 },
        ];
        const word = w(
            [
                { char: 'ل', start: 0, end: 0.2, silent: false },
                { char: 'ه', start: 0.2, end: 0.3, silent: false },
            ],
            [
                base(0, [0], { chars: 'ل' }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
                base(1, [2], { chars: 'ه' }),
                { chars: 'ُ', role: 'haraka', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 1, rules: ['pausal_sukun'], shareGroup: null },
                { chars: 'ۥ', role: 'madd', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 2, rules: ['pausal_sukun'], shareGroup: null },
                { chars: MADDAH, role: 'madd', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 2, rules: ['orthographic_silence'], shareGroup: null },
            ],
            [0, 1, 2],
        );
        const { container } = mount([word], intervals);
        const letters = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter')).map((l) => l.textContent);
        // The haa is CLEAN; the merged form never appears, and neither does a bare maddah.
        expect(letters).toContain('ه');
        expect(letters).not.toContain('ه' + MADDAH);
        expect(letters).not.toContain(MADDAH);
        // The mini-waw carrier bears the maddah.
        expect(letters).toContain('ۥ' + MADDAH);
    });

    it('hamza-waṣl ibtidaa madd (ٱئْتِ started-on): ٱ reads إ and ئ reads as the ى it carries', () => {
        // Cells as the producer stamps them: the ٱ shows the إ a reader says, the
        // quiescent ئ shows the ى the reading writes the length on, and the kasra
        // between them is not in the rasm at all. All three dashed, none greyed.
        const intervals: PhonemeInterval[] = [
            { phone: 'ʔ', start: 0, end: 0.1 },
            { phone: 'i:', start: 0.1, end: 0.4 },
            { phone: 't', start: 0.4, end: 0.5 },
        ];
        const word = w(
            [
                // the letter row keeps the rasm — it is what a consumer matches
                // its own letters against; only the cells show the reading.
                { char: 'ٱ', start: 0, end: 0.1, silent: false },
                { char: 'ئ', start: 0.1, end: 0.4, silent: false },
                { char: 'ت', start: 0.4, end: 0.5, silent: false },
            ],
            [
                base(0, [0], { chars: 'إ', status: 'replaced', rules: ['hamza_wasl_kasra'] }),
                { chars: 'ِ', role: 'haraka', status: 'inserted', phonemeIndices: [1], sourceLetterIndex: 0, rules: ['ibdal_hamza'], shareGroup: 0 },
                { chars: 'ى', role: 'madd', status: 'replaced', phonemeIndices: [1], sourceLetterIndex: 1, rules: ['ibdal_hamza'], shareGroup: 0 },
                { chars: 'ْ', role: 'haraka', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 1, rules: [], shareGroup: null },
                base(2, [2], { chars: 'ت' }),
            ],
            [0, 1, 2],
        );
        setRuleEnabled('madd_tabii', true); // colour madd-ṭabīʿī so its underline renders
        const { container } = mount([word], intervals);
        // the ئ's cell renders the ى: dashed (replaced), sounding (timed) — not greyed.
        const yaa = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter')).find((l) => l.textContent === 'ى')!;
        expect(yaa).toBeTruthy();
        expect(yaa.classList.contains('dia-replaced')).toBe(true);
        expect(yaa.classList.contains('silent')).toBe(false);
        expect(yaa.dataset.cellTimed).toBe('1');
        // the ٱ's own cell renders the إ, dashed for the same reason.
        const hamza = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter')).find((l) => l.textContent === 'إ')!;
        expect(hamza).toBeTruthy();
        expect(hamza.classList.contains('dia-replaced')).toBe(true);
        // the helping kasra is a bordered (inserted) small cell forming the
        // kasra+yaa vowel group — the FE dashes it from status alone.
        const kasra = Array.from(container.querySelectorAll<HTMLElement>('.haraka-cell')).find(
            (h) => h.textContent?.includes('ِ'),
        )!;
        expect(kasra).toBeTruthy();
        expect(kasra.classList.contains('dia-inserted')).toBe(true);
        // the sukūn rides inert and is filtered — no ئ glyph survives.
        expect(Array.from(container.querySelectorAll('.mega-letter')).some((l) => l.textContent === 'ئ')).toBe(false);
        // ʔ (idx 0, under إ), iː (idx 1, under ى), t (idx 2, under ت) each in a DISTINCT
        // cluster — not snapped onto the first letter.
        const clusters = Array.from(container.querySelectorAll<HTMLElement>('.phoneme-cluster'));
        const cl = (i: string) => clusters.findIndex((c) => c.querySelector(`.mega-phoneme[data-index="${i}"]`));
        expect(new Set([cl('0'), cl('1'), cl('2')]).size).toBe(3);
        // the iː phoneme carries the madd_tabii rule (the bug: it was tagged
        // hamza_wasl_vowel and never got the madd before) — with the rule coloured it
        // underlines on the iː itself.
        const iLong = container.querySelector<HTMLElement>('.mega-phoneme[data-index="1"]')!;
        expect(iLong.style.boxShadow).not.toBe('');
        // the prosthetic hamza stays its own base sounding ʔ.
        expect(hamza.dataset.cellTimed).toBe('1');
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
                { chars: 'ِ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: 1 },
                { chars: 'ي', role: 'madd', status: 'present', phonemeIndices: [1], sourceLetterIndex: 1, rules: [], shareGroup: 1 },
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
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
                base(1, [2], { chars: 'بّ' }),
                { chars: 'ِ', role: 'haraka', status: 'present', phonemeIndices: [3], sourceLetterIndex: 1, rules: [], shareGroup: null },
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
            { chars: 'ْ', role: 'haraka', status: 'present', phonemeIndices: [], sourceLetterIndex: 1, rules: [], shareGroup: null }, // sukūn — filtered
            base(2, [1], { chars: 'ع' }),
            { chars: 'ٰ', role: 'madd', status: 'present', phonemeIndices: [2], sourceLetterIndex: 2, rules: [], shareGroup: 0 },
            { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [2], sourceLetterIndex: 2, rules: [], shareGroup: 0 },
            base(3, [3], { chars: 'ل' }),
            { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [4], sourceLetterIndex: 3, rules: [], shareGroup: null },
            base(4, [5], { chars: 'م' }),
            { chars: 'ِ', role: 'haraka', status: 'present', phonemeIndices: [6], sourceLetterIndex: 4, rules: [], shareGroup: 1 },
            { chars: 'ي', role: 'madd', status: 'present', phonemeIndices: [6], sourceLetterIndex: 5, rules: [], shareGroup: 1 },
            base(6, [7], { chars: 'ن' }),
            { chars: 'َ', role: 'haraka', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 6, rules: [], shareGroup: null },
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
             { chars: 'ٌ', role: 'tanween', status: 'present', phonemeIndices: [1, 2], sourceLetterIndex: 0, rules: [], shareGroup: null }],
            [0, 1, 2],
        );
        let { container } = mount([izhar], intervals);
        expect(container.querySelector('.haraka-cell .g')!.textContent).toBe('ٌ');
        // two-phoneme tanwīn ([u, n]) → its dia-track fills its column (the
        // stretch is now general CSS, no per-cell class).
        expect(container.querySelector('.dia-track')!.classList.contains('wide')).toBe(false);
        cleanup();
        // idgham (assimilates into the next word) → OPEN ḍammatan (U+08F1).
        const idgham = w(
            [{ char: 'ع', start: 0, end: 0.3, silent: false }],
            [base(0, [0], { chars: 'ع' }),
             { chars: 'ٌ', role: 'tanween', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: ['idgham_bi_ghunnah'], shareGroup: null }],
            [0, 1],
        );
        ({ container } = mount([idgham], intervals));
        expect(container.querySelector('.haraka-cell .g')!.textContent).toBe(String.fromCodePoint(0x08f1));
        // single-phoneme tanwīn → still a dia-track, no per-cell stretch class.
        expect(container.querySelector('.dia-track')!.classList.contains('wide')).toBe(false);
    });

    it('madd-ʿiwaḍ: the fatḥatan reads as a dashed fatḥa beside the written alef', () => {
        // ضًا at waqf: ض base, the fatḥatan and the alef sharing the ʿiwaḍ ā.
        const intervals: PhonemeInterval[] = [
            { phone: 'dˤ', start: 0, end: 0.2 }, { phone: 'aˤ:', start: 0.2, end: 0.6 },
        ];
        const word = w(
            [{ char: 'ض', start: 0, end: 0.2, silent: false }, { char: 'ا', start: 0.2, end: 0.6, silent: false }],
            [
                base(0, [0], { chars: 'ض' }),
                { chars: 'ً', role: 'tanween', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: ['madd_iwad'], shareGroup: 0 },
                { chars: 'ا', role: 'madd', status: 'present', phonemeIndices: [1], sourceLetterIndex: 1, rules: ['madd_iwad'], shareGroup: 0 },
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
        const alef = vowel.querySelector<HTMLElement>('.mega-letter')!;
        expect(alef.textContent).toBe('ا');
        // the alef IS in the rasm, so it is not dashed; the fatḥa is not, so it is.
        expect(alef.classList.contains('dia-inserted')).toBe(false);
        const fatha = vowel.querySelector<HTMLElement>('.haraka-cell')!;
        expect(fatha.classList.contains('dia-inserted')).toBe(true);
        expect(fatha.dataset.cellTimed).toBe('1');
        expect(fatha.dataset.cellStart).toBe('0.2');
        // the ʿiwaḍ sound spans the WHOLE [fatḥa, alef] group (same width as the unit).
        expect(vowel.querySelectorAll('.phoneme-cluster').length).toBe(1);
        expect(vowel.querySelector<HTMLElement>('.phoneme-cluster')!.style.gridColumn
            .replace(/\s+/g, ' ').trim()).toBe('1 / span 2');
    });

    it('madd-ʿiwaḍ at hamza waqf: BOTH the fatḥa and the inserted alef are dashed', () => {
        // مَآءً at waqf ends in hamza with NO written alef: ء base, the fatḥatan,
        // and a graphemeless alef the stop supplies. Neither the fatḥa nor the
        // alef is what the mushaf writes, so both carry the dashed border.
        const intervals: PhonemeInterval[] = [
            { phone: 'ʔ', start: 0, end: 0.2 }, { phone: 'a:', start: 0.2, end: 0.6 },
        ];
        const word = w(
            [{ char: 'ء', start: 0, end: 0.2, silent: false }],
            [
                base(0, [0], { chars: 'ء' }),
                { chars: 'َ', role: 'haraka', status: 'replaced', phonemeIndices: [1], sourceLetterIndex: 0, rules: ['madd_iwad', 'madd_tabii'], shareGroup: 0 },
                { chars: 'ا', role: 'madd', status: 'inserted', phonemeIndices: [1], sourceLetterIndex: 0, rules: ['madd_iwad', 'madd_tabii'], shareGroup: 0 },
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
        // the fatḥa co-lights on the alef's long ā (timed, not greyed) AND is
        // itself dashed: the mushaf writes a fatḥatan, not a fatḥa.
        const fatha = vowel.querySelector<HTMLElement>('.haraka-cell')!;
        expect(fatha.dataset.cellTimed).toBe('1');
        expect(fatha.dataset.cellStart).toBe('0.2');
        expect(fatha.classList.contains('dia-replaced')).toBe(true);
        // the ʿiwaḍ sound spans the WHOLE [fatḥa, implicit-alef] group.
        expect(vowel.querySelectorAll('.phoneme-cluster').length).toBe(1);
        expect(vowel.querySelector<HTMLElement>('.phoneme-cluster')!.style.gridColumn
            .replace(/\s+/g, ' ').trim()).toBe('1 / span 2');
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
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
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
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [3], sourceLetterIndex: 0, rules: [], shareGroup: 9 },
                { chars: 'آ', role: 'madd', status: 'present', phonemeIndices: [3], sourceLetterIndex: 1, rules: [], shareGroup: 9 },
                base(2, [4], { chars: 'ء' }),
                { chars: 'َ', role: 'haraka', status: 'replaced', phonemeIndices: [5], sourceLetterIndex: 2, rules: ['madd_iwad', 'madd_tabii'], shareGroup: 0 },
                { chars: 'ا', role: 'madd', status: 'inserted', phonemeIndices: [5], sourceLetterIndex: 2, rules: ['madd_iwad', 'madd_tabii'], shareGroup: 0 },
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

    it('idgham shafawi: the receiving meem owns no phoneme and co-lights via the merger union (not greyed)', () => {
        // …هِم مَّرَض — the geminated m̃ lives on the SOURCE meem (word A); the receiving
        // meem (word B) carries NO phoneme and co-lights purely through the shared merger
        // group, exactly like an idgham-noon receiver — so it must not grey out, and it
        // spans the m̃ union [0, 0.1], NOT the following vowel.
        const intervals: PhonemeInterval[] = [
            { phone: 'm̃', start: 0, end: 0.1 },   // the merged nasal (source meem)
            { phone: 'a', start: 0.1, end: 0.25 }, // the receiving meem's vowel
        ];
        const him = w(
            [{ char: 'م', start: 0, end: 0.1, silent: false }],
            [base(0, [0], { chars: 'م', rules: ['idgham_shafawi'], shareGroup: 5 })],
            [0],
        );
        const marad = w(
            [{ char: 'م', start: 0.1, end: 0.25, silent: false }],
            [
                base(0, [], { chars: 'م', shareGroup: 5 }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
            ],
            [1],
        );
        const { container } = mount([him, marad], intervals);
        const meems = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .filter((el) => el.textContent === 'م');
        expect(meems.length).toBe(2);
        for (const m of meems) {
            expect(m.classList.contains('silent')).toBe(false);
            expect(m.dataset.cellTimed).toBe('1');
            expect(m.dataset.cellStart).toBe('0');
            expect(m.dataset.cellEnd).toBe('0.1'); // the m̃ union — NOT the vowel
        }
    });

    it('share group: a tag-less co-lit partner inherits the group rule so report mode can select it', () => {
        // A madd letter (carries the rule) co-lights with its vowel (no own tag)
        // through one share group. In report mode BOTH must be flaggable as that
        // shared rule — the partner must expose data-has-tj='1' + the rule rules: [tag],
        // not just the cell that literally owns the tag.
        const intervals: PhonemeInterval[] = [
            { phone: 'a', start: 0, end: 0.1 },
            { phone: 'aː', start: 0.1, end: 0.4 },
        ];
        const word = w(
            [{ char: 'ب', start: 0, end: 0.1, silent: false }, { char: 'ا', start: 0.1, end: 0.4, silent: false }],
            [
                base(0, [0], { chars: 'ب' }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [0], sourceLetterIndex: 0, rules: [], shareGroup: 3 },
                base(1, [1], { chars: 'ا', rules: ['madd_tabii'], shareGroup: 3 }),
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        const vowel = container.querySelector<HTMLElement>('.haraka-cell')!;
        expect(vowel.dataset.hasTj).toBe('1');
        expect(vowel.dataset.tjTags).toContain('madd_tabii');
        const maddLetter = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .find((e) => e.textContent === 'ا')!;
        expect(maddLetter.dataset.hasTj).toBe('1');
    });

    it('idgham shafawi: the absorbed vowel lights on its own haraka interval, disjoint from the meems', () => {
        // The vowel now lives ONLY on the receiving meem's haraka (its own interval, no
        // merger group). Looping the haraka lights its vowel [0.1, 0.25] without
        // intersecting either meem's cell span (the m̃ union [0, 0.1]).
        const intervals: PhonemeInterval[] = [
            { phone: 'm̃', start: 0, end: 0.1 },
            { phone: 'a', start: 0.1, end: 0.25 },
        ];
        const him = w(
            [{ char: 'م', start: 0, end: 0.1, silent: false }],
            [base(0, [0], { chars: 'م', rules: ['idgham_shafawi'], shareGroup: 5 })],
            [0],
        );
        const marad = w(
            [{ char: 'م', start: 0.1, end: 0.25, silent: false }],
            [
                base(0, [], { chars: 'م', shareGroup: 5 }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
            ],
            [1],
        );
        const { container } = mount([him, marad], intervals);
        const fatha = container.querySelector<HTMLElement>('.haraka-cell')!;
        expect(fatha.classList.contains('dia-dropped')).toBe(false);
        expect(fatha.dataset.cellTimed).toBe('1');
        // OWN vowel interval [0.1, 0.25], disjoint from the meems.
        expect(fatha.dataset.cellStart).toBe('0.1');
        expect(fatha.dataset.cellEnd).toBe('0.25');
        // the meems span only the m̃ union [0, 0.1].
        const meem = container.querySelector<HTMLElement>('.mega-letter[data-cell-timed]')!;
        expect(meem.dataset.cellStart).toBe('0');
        expect(meem.dataset.cellEnd).toBe('0.1');
    });

    it('idgham shafawi into a long vowel (مَّا): the receiving meem co-lights, not greyed', () => {
        // …م مَّا — the receiving meem owns NO phoneme and the following long vowel sits
        // on its own alef (aː), so the meem must still link to the source meem and
        // co-light via the merger union [0, 0.2], NOT grey out as a silent letter.
        const intervals: PhonemeInterval[] = [
            { phone: 'm̃', start: 0, end: 0.2, bridge: 'idgham_shafawi' }, // merged nasal, lifted to the bridge
            { phone: 'a:', start: 0.2, end: 0.5 },  // the long vowel, on the alef
        ];
        const him = w(
            [{ char: 'م', start: 0, end: 0.2, silent: false }],
            [base(0, [0], { chars: 'م', rules: ['idgham_shafawi'], shareGroup: 5 })],
            [0],
        );
        const maa = w(
            [
                { char: 'م', start: 0.2, end: 0.5, silent: false },
                { char: 'ا', start: 0.2, end: 0.5, silent: false },
            ],
            [
                base(0, [], { chars: 'م', status: 'dropped', shareGroup: 5 }), // receiver: co-lit via union
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: 6 },
                { chars: 'ا', role: 'madd', status: 'present', phonemeIndices: [1], sourceLetterIndex: 1, rules: [], shareGroup: 6 },
            ],
            [1],
        );
        const { container } = mount([him, maa], intervals);
        const meems = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .filter((el) => el.textContent === 'م');
        expect(meems.length).toBe(2);
        for (const m of meems) {
            expect(m.classList.contains('silent')).toBe(false); // co-lit, not greyed
            expect(m.dataset.cellTimed).toBe('1');
            expect(m.dataset.cellStart).toBe('0');
            expect(m.dataset.cellEnd).toBe('0.2'); // the m̃ union, not the aː
        }
        // the aː rides the alef (its own long-vowel group), not the meem.
        expect(container.querySelector<HTMLElement>('.mega-letter')!).toBeTruthy();
        const alef = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .find((el) => el.textContent === 'ا')!;
        expect(alef.dataset.cellStart).toBe('0.2');
        expect(alef.dataset.cellEnd).toBe('0.5');
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
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
                base(1, [], { chars: 'ن', status: 'dropped', rules: ['idgham_bi_ghunnah'], shareGroup: 5 }),
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

    it('qalqala: BOTH the consonant cell duration AND its letter timing include the render-only Q echo', () => {
        // قْد at sukūn: ق sounds [q] (idx 0) then the render-only echo [Q] (idx 1, in NO
        // cell's phonemeIndices), then د [d]. The qāf cell's HIGHLIGHT span (cellStart/
        // cellEnd) AND its LETTER span (click/loop/tooltip) both stretch over q+Q
        // ([0, 0.15]) — the consonant and its echo loop/seek as one unit.
        const intervals: PhonemeInterval[] = [
            { phone: 'q', start: 0, end: 0.1 },
            { phone: 'Q', start: 0.1, end: 0.15 },
            { phone: 'd', start: 0.15, end: 0.3 },
        ];
        const word = w(
            [{ char: 'ق', start: 0, end: 0.1, silent: false }, { char: 'د', start: 0.15, end: 0.3, silent: false }],
            [
                base(0, [0], { chars: 'ق', rules: ['qalqala_sughra'] }), // ق owns only q (idx 0), not Q
                { chars: 'ْ', role: 'haraka', status: 'present', phonemeIndices: [], sourceLetterIndex: 0, rules: [], shareGroup: null }, // sukūn
                base(1, [2], { chars: 'د' }),
            ],
            [0, 2], // Q (idx 1) is rendered but indexed by no cell
        );
        const { container } = mount([word], intervals);
        const qaf = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter[data-cell-timed]'))
            .find((el) => el.textContent === 'ق')!;
        expect(qaf).toBeTruthy();
        // HIGHLIGHT span covers q (0..0.1) AND the Q echo (0.1..0.15).
        expect(qaf.dataset.cellStart).toBe('0');
        expect(qaf.dataset.cellEnd).toBe('0.15');
        // LETTER span (click/loop/tooltip) also stretches over the Q echo.
        expect(qaf.dataset.letterStart).toBe('0');
        expect(qaf.dataset.letterEnd).toBe('0.15');
    });

    it('qalqala: a non-qalqala consonant ignores a following Q echo (no over-extend)', () => {
        // Guard: only a qalqala-tagged cell unions the Q. A plain consonant followed
        // by a Q in intervals[] keeps its own [start,end].
        const intervals: PhonemeInterval[] = [
            { phone: 'q', start: 0, end: 0.1 },
            { phone: 'Q', start: 0.1, end: 0.15 },
        ];
        const word = w(
            [{ char: 'ق', start: 0, end: 0.1, silent: false }],
            [base(0, [0], { chars: 'ق' })], // NO qalqala tag
            [0],
        );
        const { container } = mount([word], intervals);
        const qaf = container.querySelector<HTMLElement>('.mega-letter[data-cell-timed]')!;
        expect(qaf.dataset.cellStart).toBe('0');
        expect(qaf.dataset.cellEnd).toBe('0.1'); // own interval, echo NOT unioned
    });

    it('Allah: the fatḥa and the implicit dagger-alef share one vowel group', () => {
        // …للَّه as the producer writes it: the fatḥa keeps the sound it opens and
        // the alif nobody wrote shares it, the same pair a written dagger gives.
        const intervals: PhonemeInterval[] = [
            { phone: 'll', start: 0, end: 0.15 }, { phone: 'a:', start: 0.15, end: 0.5 },
        ];
        const word = w(
            [{ char: 'ل', start: 0, end: 0.5, silent: false }, { char: 'ه', start: 0.5, end: 0.6, silent: false }],
            [
                base(0, [0], { chars: 'ل' }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: ['madd_tabii'], shareGroup: 1 },
                { chars: 'ا', role: 'madd', status: 'inserted', phonemeIndices: [1], sourceLetterIndex: 0, rules: ['madd_tabii'], shareGroup: 1 },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        const vowel = Array.from(container.querySelectorAll<HTMLElement>('.cell-group')).find(
            (g) => g.querySelector('.mega-letter.implicit'),
        )!;
        expect(vowel).toBeTruthy();
        expect(vowel.querySelector<HTMLElement>('.mega-letter.implicit')!.textContent).toBe('ٰ');
        const fatha = vowel.querySelector<HTMLElement>('.haraka-cell')!;
        expect(fatha).toBeTruthy();
        expect(fatha.dataset.cellStart).toBe('0.15');
        // one sound across the whole [fatḥa, alif] group, as a written dagger gives.
        expect(vowel.querySelectorAll('.phoneme-cluster').length).toBe(1);
        expect(vowel.querySelector<HTMLElement>('.phoneme-cluster')!.style.gridColumn
            .replace(/\s+/g, ' ').trim()).toBe('1 / span 2');
    });

    it('renders one cell-group per letter-group, each holding its base + pinned diacritic', () => {
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
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
                base(1, [2]),
            ],
            [0, 1, 2],
        );
        const { container } = mount([word], intervals);
        const groups = container.querySelectorAll<HTMLElement>('.cell-group');
        expect(groups.length).toBe(2);
        // Gap WITHIN a group is 0 (CSS `gap: 0`); the between-group gap is the grid
        // column-gap. Each group holds its base + its pinned diacritic, no nesting.
        const first = groups[0]!;
        // first group has base + small inside it, no nested stack.
        expect(first.querySelector('.mega-letter')).toBeTruthy();
        expect(first.querySelector('.dia-track')).toBeTruthy();
    });

    it('seeks to a diacritic cell on click (cellStart × 1000), after the click-defer delay', async () => {
        // بَ : ب base, fatḥa on phoneme idx 1 (start 0.1s). Clicking the small
        // fatḥa cell seeks to 0.1s = 100ms (tsSegOffset 0), not the word start.
        // The single-click is DEFERRED (TS_CLICK_DELAY_MS) to disambiguate from a
        // dblclick, so the seek fires only after the timer advances.
        const intervals: PhonemeInterval[] = [
            { phone: 'b', start: 0, end: 0.1 }, { phone: 'a', start: 0.1, end: 0.35 },
        ];
        const word = w(
            [{ char: 'ب', start: 0, end: 0.35, silent: false }],
            [
                base(0, [0]),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
            ],
            [0, 1],
        );
        const seekSpy = vi.spyOn(dashPort, 'seek').mockImplementation(() => {});
        vi.useFakeTimers();
        try {
            const { container } = mount([word], intervals);
            const haraka = container.querySelector<HTMLElement>('.haraka-cell.dia-seekable')!;
            expect(haraka).toBeTruthy();
            await fireEvent.click(haraka);
            await vi.advanceTimersByTimeAsync(TS_CLICK_DELAY_MS + 1);
            expect(seekSpy).toHaveBeenCalledWith(100);
        } finally {
            vi.useRealTimers();
        }
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
                    { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
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

    // --- Tajweed-rule underlines (per-cell box-shadow stack) ----------------

    it('madd: badges the carrier grapheme + its phoneme box, NOT the haraka', () => {
        const intervals: PhonemeInterval[] = [
            { phone: 'dˤ', start: 0, end: 0.1 }, { phone: 'a:', start: 0.1, end: 0.5 },
        ];
        const word = w(
            [{ char: 'ض', start: 0, end: 0.1, silent: false }, { char: 'ا', start: 0.1, end: 0.5, silent: false }],
            [
                base(0, [0], { chars: 'ض' }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: 0 },
                { chars: 'ا', role: 'madd', status: 'present', phonemeIndices: [1], sourceLetterIndex: 1, rules: ['madd_wajib_muttasil'], shareGroup: 0 },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        const carrier = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .find((e) => e.textContent === 'ا')!;
        expect(carrier.style.boxShadow).not.toBe('');
        expect(carrier.style.boxShadow).toContain('madd-wajib');
        // the haraka co-lights but is NOT coloured (madd = carrier grapheme only)
        const haraka = container.querySelector<HTMLElement>('.haraka-cell')!;
        expect(haraka.style.boxShadow).toBe('');
        // the long-vowel phoneme box is badged
        expect(container.querySelector<HTMLElement>('.mega-phoneme[data-index="1"]')!.style.boxShadow).not.toBe('');
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
                { chars: 'ٍ', role: 'tanween', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: ['idgham_bi_ghunnah'], shareGroup: 7 },
            ],
            [0, 1],
        );
        const wordN1 = w(
            [{ char: 'م', start: 0.2, end: 0.6, silent: false }],
            [base(0, [2], { chars: 'م', shareGroup: 7 })],
            [2],
        );
        const { container } = mount([wordN, wordN1], intervals);
        expect(container.querySelector<HTMLElement>('.haraka-cell')!.style.boxShadow).not.toBe(''); // tanwīn source
        const meem = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .find((e) => e.textContent === 'م')!;
        expect(meem.style.boxShadow).not.toBe('');                                                  // receiver, via group
        expect(container.querySelector<HTMLElement>('.crossword-bridge .mega-phoneme')!.style.boxShadow).not.toBe('');
        // the source tanwīn's own vowel box is NOT badged (its merger is the bridge)
        expect(container.querySelector<HTMLElement>('.mega-phoneme[data-index="1"]')!.style.boxShadow).toBe('');
    });

    it('idgham shafawi: both mīms badged + the single bridge tile', () => {
        const intervals: PhonemeInterval[] = [
            { phone: 'h', start: 0, end: 0.1 },
            { phone: 'm̃', start: 0.1, end: 0.5, bridge: 'idgham_shafawi' }, // source-mīm merger (bridge)
            { phone: 'a', start: 0.5, end: 0.6 },                           // receiver mīm's vowel
        ];
        const wordN = w(
            [{ char: 'ه', start: 0, end: 0.1, silent: false }, { char: 'م', start: 0.1, end: 0.5, silent: false }],
            [base(0, [0], { chars: 'ه' }), base(1, [1], { chars: 'م', rules: ['idgham_shafawi'], shareGroup: 8 })],
            [0, 1],
        );
        const wordN1 = w(
            [{ char: 'م', start: 0.5, end: 0.6, silent: false }],
            [
                base(0, [], { chars: 'م', shareGroup: 8 }), // receiver: no phoneme, co-lit via union
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [2], sourceLetterIndex: 0, rules: [], shareGroup: null },
            ],
            [2],
        );
        const { container } = mount([wordN, wordN1], intervals);
        const meems = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .filter((e) => e.textContent === 'م');
        expect(meems.length).toBe(2);
        expect(meems.every((m) => m.style.boxShadow !== '')).toBe(true);
        const bridge = container.querySelector<HTMLElement>('.crossword-bridge .mega-phoneme')!;
        expect(bridge.style.boxShadow).not.toBe('');
        expect(bridge.style.boxShadow).toContain('idgham-shafawi');
    });

    it('Allah dagger: takes the rule its haraka takes — ṭabīʿī continuing, arid at waqf', () => {
        const intervals: PhonemeInterval[] = [
            { phone: 'll', start: 0, end: 0.15 }, { phone: 'a:', start: 0.15, end: 0.5 },
        ];
        // The pair share one sound, so they carry one rule between them and both
        // draw it — the same as a WRITTEN dagger (ذَٰلِكَ), which is the point.
        const mk = (tag: string) => w(
            [{ char: 'ل', start: 0, end: 0.5, silent: false }, { char: 'ه', start: 0.5, end: 0.6, silent: false }],
            [
                base(0, [0], { chars: 'ل' }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [tag], shareGroup: 1 },
                { chars: '', role: 'madd', status: 'inserted', phonemeIndices: [1], sourceLetterIndex: 0, rules: [tag], shareGroup: 1 },
            ],
            [0, 1],
        );
        setRuleEnabled('madd_tabii', true); // off by default — it is on nearly every word
        let c = mount([mk('madd_tabii')], intervals).container;
        expect(c.querySelector<HTMLElement>('.mega-letter.implicit')!.style.boxShadow)
            .toContain('madd-tabii');
        cleanup();
        resetAllTajweed();
        c = mount([mk('madd_arid_lil_sukun')], intervals).container;
        const vowel = Array.from(c.querySelectorAll<HTMLElement>('.cell-group')).find(
            (g) => g.querySelector('.mega-letter.implicit'),
        )!;
        expect(vowel.querySelector<HTMLElement>('.mega-letter.implicit')!.style.boxShadow)
            .toContain('madd-arid');
        const fatha = vowel.querySelector<HTMLElement>('.haraka-cell')!;
        expect(fatha.classList.contains('dia-dropped')).toBe(false);
        expect(fatha.dataset.cellTimed).toBe('1');
        expect(fatha.dataset.cellStart).toBe('0.15'); // the ā it opens
        expect(fatha.style.boxShadow).toContain('madd-arid');
    });

    it('no underline for an untagged madd carrier (no rule on the cell)', () => {
        const tabiiIv: PhonemeInterval[] = [
            { phone: 'q', start: 0, end: 0.1 }, { phone: 'a:', start: 0.1, end: 0.4 },
        ];
        const tabii = w(
            [{ char: 'ق', start: 0, end: 0.1, silent: false }, { char: 'ا', start: 0.1, end: 0.4, silent: false }],
            [
                base(0, [0], { chars: 'ق' }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: 0 },
                { chars: 'ا', role: 'madd', status: 'present', phonemeIndices: [1], sourceLetterIndex: 1, rules: [], shareGroup: 0 },
            ],
            [0, 1],
        );
        expect(anyBadge(mount([tabii], tabiiIv).container)).toBe(false);
    });

    it('bila-ghunnah idgham underlines the source tanwīn, its receiver, and the bridge', () => {
        const bilaIv: PhonemeInterval[] = [
            { phone: 'b', start: 0, end: 0.1 }, { phone: 'i', start: 0.1, end: 0.2 },
            { phone: 'rˤrˤ', start: 0.2, end: 0.5, bridge: 'idgham_bila_ghunnah_tanween' },
        ];
        const bN = w(
            [{ char: 'ب', start: 0, end: 0.2, silent: false }],
            [
                base(0, [0], { chars: 'ب' }),
                { chars: 'ٍ', role: 'tanween', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: ['idgham_bila_ghunnah'], shareGroup: 7 },
            ],
            [0, 1],
        );
        const bN1 = w(
            [{ char: 'ر', start: 0.2, end: 0.5, silent: false }],
            [base(0, [2], { chars: 'ر', shareGroup: 7 })],
            [2],
        );
        const { container } = mount([bN, bN1], bilaIv);
        // source tanwīn cell (the haraka) underlines bila-ghunnah
        expect(container.querySelector<HTMLElement>('.haraka-cell')!.style.boxShadow).toContain('idgham-bila');
        // receiver ر picks the colour up via its share group
        const recv = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter')).find((e) => e.textContent === 'ر')!;
        expect(recv.style.boxShadow).toContain('idgham-bila');
        // the merged bridge tile underlines too
        expect(container.querySelector<HTMLElement>('.crossword-bridge .mega-phoneme')!.style.boxShadow).toContain('idgham-bila');
    });

    it('stacks tafkheem above its base rule — qalqala below, tafkheem the upper bar', () => {
        const iv: PhonemeInterval[] = [
            { phone: 'q', start: 0, end: 0.1 }, { phone: 'Q', start: 0.1, end: 0.15 },
        ];
        const word = w(
            [{ char: 'ق', start: 0, end: 0.15, silent: false }],
            [base(0, [0], { chars: 'ق', rules: ['qalqala_sughra', 'tafkheem'] })],
            [0],
        );
        const { container } = mount([word], iv);
        const letter = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter')).find((e) => e.textContent === 'ق')!;
        const shadow = letter.style.boxShadow;
        expect(shadow).toContain('var(--tj-qalqala)');
        expect(shadow).toContain('var(--tj-tafkheem)');
        // qalqala is listed first (bottom bar), tafkheem second (above it)
        expect(shadow.indexOf('qalqala')).toBeLessThan(shadow.indexOf('tafkheem'));
        // the tooltip names both rules, ms line first
        expect(letter.dataset.tjRules).toBe('Qalqala Sughra\nTafkheem');
    });

    it('qalqala underlines the render-only Q echo phoneme, not the consonant phoneme', () => {
        const iv: PhonemeInterval[] = [
            { phone: 'q', start: 0, end: 0.1 }, { phone: 'Q', start: 0.1, end: 0.15 },
        ];
        const word = w(
            [{ char: 'ق', start: 0, end: 0.15, silent: false }],
            [base(0, [0], { chars: 'ق', rules: ['qalqala_sughra'] })],
            [0, 1], // both the consonant phone and its Q echo render
        );
        const { container } = mount([word], iv);
        const ph = (i: number) => container.querySelector<HTMLElement>(`.mega-phoneme[data-index="${i}"]`);
        expect(ph(0)?.style.boxShadow ?? '').toBe('');           // consonant: no qalqala
        expect(ph(1)!.style.boxShadow).toContain('qalqala');     // Q echo: qalqala
        // the letter itself still carries the qalqala underline
        const letter = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter')).find((e) => e.textContent === 'ق')!;
        expect(letter.style.boxShadow).toContain('qalqala');
    });

    it('a trailing dropped ḥaraka at a stop shows the "Waqf" tooltip, no underline', () => {
        const iv: PhonemeInterval[] = [{ phone: 'n', start: 0, end: 0.2 }];
        const word = w(
            [{ char: 'ن', start: 0, end: 0.2, silent: false }],
            [
                base(0, [0], { chars: 'ن' }),
                { chars: 'َ', role: 'haraka', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 0, rules: ['pausal_sukun'], shareGroup: null },
            ],
            [0],
        );
        const drop = mount([word], iv).container.querySelector<HTMLElement>('.haraka-cell')!;
        expect(drop.dataset.tjRules).toBe('Waqf');
        expect(drop.style.boxShadow).toBe('');
    });

    it('a silent ʿiwaḍ alef after a tanwīn (waṣl) shows "Madd \'Iwad Wasl"', () => {
        const iv: PhonemeInterval[] = [
            { phone: 'm', start: 0, end: 0.1 }, { phone: 'a', start: 0.1, end: 0.15 }, { phone: 'n', start: 0.15, end: 0.2 },
        ];
        const word = w(
            [{ char: 'م', start: 0, end: 0.1, silent: false }, { char: 'ا', start: null, end: null, silent: true }],
            [
                base(0, [0], { chars: 'م' }),
                { chars: 'ً', role: 'tanween', status: 'present', phonemeIndices: [1, 2], sourceLetterIndex: 0, rules: [], shareGroup: null },
                { chars: 'ا', role: 'base', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 1, rules: ['orthographic_silence'], shareGroup: null },
            ],
            [0, 1, 2],
        );
        const { container } = mount([word], iv);
        const alef = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter')).find((e) => e.textContent === 'ا')!;
        expect(alef.dataset.tjRules).toBe("Silent Letter");
    });

    it('a silent-rule letter (lām shamsiyyah) shows a rule tooltip with no underline', () => {
        const iv: PhonemeInterval[] = [{ phone: 'ʃ', start: 0, end: 0.2 }];
        const word = w(
            [{ char: 'ل', start: null, end: null, silent: true }, { char: 'ش', start: 0, end: 0.2, silent: false }],
            [
                { chars: 'ل', role: 'base', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 0, rules: ['lam_shamsiyyah'], shareGroup: null },
                base(1, [0], { chars: 'ش' }),
            ],
            [0],
        );
        const { container } = mount([word], iv);
        const lam = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter')).find((e) => e.textContent === 'ل')!;
        expect(lam.style.boxShadow).toBe(''); // silent rule → no underline
        expect(lam.dataset.tjRules).toBe('Lam Shamsiyyah');
    });

    it('iẓhar: a sakin noon badges letter + phoneme in halqi blue', () => {
        setRuleEnabled('izhar', true); // iẓhar is an opt-in (default off) rule
        // مِنْ — a sakin nūn (no own haraka, just a sukūn) that SOUNDS: the producer
        // fires `izhar`. Both the ن letter and its n phoneme underline.
        const intervals: PhonemeInterval[] = [
            { phone: 'm', start: 0, end: 0.1 }, { phone: 'i', start: 0.1, end: 0.2 },
            { phone: 'n', start: 0.2, end: 0.4 },
        ];
        const word = w(
            [{ char: 'م', start: 0, end: 0.2, silent: false }, { char: 'ن', start: 0.2, end: 0.4, silent: false }],
            [
                base(0, [0], { chars: 'م' }),
                { chars: 'ِ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
                base(1, [2], { chars: 'ن', rules: ['izhar'] }),
                { chars: 'ْ', role: 'haraka', status: 'present', phonemeIndices: [], sourceLetterIndex: 1, rules: [], shareGroup: null },
            ],
            [0, 1, 2],
        );
        const { container } = mount([word], intervals);
        const noon = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .find((e) => e.textContent === 'ن')!;
        expect(noon.style.boxShadow).not.toBe('');
        expect(noon.style.boxShadow).toContain('izhar-halqi');
        const nPhone = container.querySelector<HTMLElement>('.mega-phoneme[data-index="2"]')!;
        expect(nPhone.style.boxShadow).not.toBe('');
        expect(nPhone.style.boxShadow).toContain('izhar-halqi');
    });

    it('iẓhar shafawi: a sakin meem badges in the shafawi blue', () => {
        setRuleEnabled('izhar_shafawi', true); // iẓhar shafawi is opt-in (default off)
        const intervals: PhonemeInterval[] = [
            { phone: 'h', start: 0, end: 0.1 }, { phone: 'u', start: 0.1, end: 0.2 },
            { phone: 'm', start: 0.2, end: 0.4 },
        ];
        const word = w(
            [{ char: 'ه', start: 0, end: 0.2, silent: false }, { char: 'م', start: 0.2, end: 0.4, silent: false }],
            [
                base(0, [0], { chars: 'ه' }),
                { chars: 'ُ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
                base(1, [2], { chars: 'م', rules: ['izhar_shafawi'] }),
                { chars: 'ْ', role: 'haraka', status: 'present', phonemeIndices: [], sourceLetterIndex: 1, rules: [], shareGroup: null },
            ],
            [0, 1, 2],
        );
        const { container } = mount([word], intervals);
        const meem = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .find((e) => e.textContent === 'م')!;
        expect(meem.style.boxShadow).not.toBe('');
        expect(meem.style.boxShadow).toContain('izhar-shafawi');
    });

    it('no iẓhar for a VOWELED noon (not sakin) nor a mushaddad noon (ghunnah)', () => {
        // نَ : a fatḥa-voweled nūn → not sakin → the producer fires no rule at all.
        const intervals: PhonemeInterval[] = [
            { phone: 'n', start: 0, end: 0.1 }, { phone: 'a', start: 0.1, end: 0.2 },
        ];
        const word = w(
            [{ char: 'ن', start: 0, end: 0.2, silent: false }],
            [
                base(0, [0], { chars: 'ن' }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
            ],
            [0, 1],
        );
        expect(anyBadge(mount([word], intervals).container)).toBe(false);
    });

    it('ghunnah merger bridge: an uncoloured idgham rule whose receiver sounds a nasal still badges the bridge phoneme', () => {
        // ٱرْكَب مَّعَنَا: ب → مّ (idgham_mutajanisayn_kamil, uncoloured). The receiving
        // مّ carries ghunnah → its lifted m̃ bridge phoneme borrows that hue so
        // BOTH letter and bridge phoneme underline.
        const intervals: PhonemeInterval[] = [
            { phone: 'b', start: 0, end: 0.1 },
            { phone: 'm̃', start: 0.1, end: 0.5, bridge: 'idgham_mutajanisayn_kamil' },
            { phone: 'a', start: 0.5, end: 0.6 },
        ];
        const wordN = w(
            [{ char: 'ب', start: 0, end: 0.1, silent: true }],
            [base(0, [], { chars: 'ب', rules: ['idgham_mutajanisayn_kamil'] })],
            [],
        );
        const wordN1 = w(
            [{ char: 'م', start: 0.1, end: 0.5, silent: false }],
            [
                base(0, [1], { chars: 'مّ', rules: ['ghunnah'] }),
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [2], sourceLetterIndex: 0, rules: [], shareGroup: null },
            ],
            [1, 2],
        );
        const { container } = mount([wordN, wordN1], intervals);
        const meem = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .find((e) => e.textContent === 'مّ')!;
        expect(meem.style.boxShadow).not.toBe('');
        expect(meem.style.boxShadow).toContain('ghunnah');
        const bridge = container.querySelector<HTMLElement>('.crossword-bridge .mega-phoneme')!;
        expect(bridge.style.boxShadow).not.toBe('');
        expect(bridge.style.boxShadow).toContain('ghunnah');
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
                { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: ['iltiqaa'], shareGroup: null },
                { chars: 'ا', role: 'madd', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 1, rules: ['iltiqaa'], shareGroup: null },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        const alef = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .find((e) => e.textContent === 'ا')!;
        expect(alef).toBeTruthy();
        expect(alef.classList.contains('silent')).toBe(true);
    });

    it('ghunnah tanwīn (ikhfaa/iqlab): the phoneme row underlines only the nasal, not the vowel', () => {
        // بَعُوضَةً-style: the tanwīn sounds [short-vowel, nasal]. A ghunnah is ONE
        // phoneme on the phoneme row — only the nasal (idx 4) is underlined; the
        // tanwīn's own vowel (idx 3) is not (it's the letter's, not the rule's).
        const mk = (tag: string) => {
            const intervals: PhonemeInterval[] = [
                { phone: 'dˤ', start: 0, end: 0.1 }, { phone: 'a', start: 0.1, end: 0.2 },
                { phone: 't', start: 0.2, end: 0.3 },
                { phone: 'a', start: 0.3, end: 0.34 }, // tanwīn vowel
                { phone: 'ŋ', start: 0.34, end: 0.8 }, // tanwīn nasal
            ];
            const word = w(
                [{ char: 'ض', start: 0, end: 0.2, silent: false }, { char: 'ة', start: 0.2, end: 0.34, silent: false }],
                [
                    base(0, [0], { chars: 'ض' }),
                    { chars: 'َ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
                    base(1, [2], { chars: 'ة' }),
                    { chars: 'ً', role: 'tanween', status: 'present', phonemeIndices: [3, 4], sourceLetterIndex: 1, rules: [tag], shareGroup: null },
                ],
                [0, 1, 2, 3, 4],
            );
            return mount([word], intervals).container;
        };
        for (const tag of ['ikhfaa', 'iqlab']) {
            const c = mk(tag);
            expect(c.querySelector<HTMLElement>('.mega-phoneme[data-index="4"]')!.style.boxShadow).not.toBe(''); // nasal
            expect(c.querySelector<HTMLElement>('.mega-phoneme[data-index="3"]')!.style.boxShadow).toBe(''); // vowel
            cleanup();
        }
    });

    // --- Muqattaat: one cell per written mark ------------------------------
    // A letter name sounds several phones under one glyph. The shard gives the
    // letter a `base` cell spanning all of them plus a separate `madd` cell for
    // the maddah, whose narrower `phonemeIndices` pin the madd to the long vowel
    // it stretches. The letter row folds the maddah back onto its letter.

    it('muqattaat: the maddah cell pins the madd to the vowel it stretches (الٓمٓ lām)', () => {
        // الٓمٓ lām sounds [l, aː, m]; the closing mīm merges into the next mīm
        // (idgham shafawi). The lām base carries both rules over all three phones;
        // its maddah cell carries madd_lazim over the long vowel alone.
        const intervals: PhonemeInterval[] = [
            { phone: 'ʔ', start: 0, end: 0.05 },  // leading alif (base, uncoloured)
            { phone: 'l', start: 0.05, end: 0.1 },
            { phone: 'a:', start: 0.1, end: 0.7 },
            { phone: 'm', start: 0.7, end: 1.0 },
        ];
        const word = w(
            [{ char: 'ا', start: 0, end: 0.05, silent: false }, { char: 'لٓ', start: 0.05, end: 1.0, silent: false }],
            [
                base(0, [0], { chars: 'ا' }),
                {
                    chars: 'ل', role: 'base', status: 'present', phonemeIndices: [1, 2, 3],
                    sourceLetterIndex: 1, rules: ['idgham_shafawi', 'madd_lazim'], shareGroup: null,
                },
                {
                    chars: 'ٓ', role: 'madd', status: 'present', phonemeIndices: [2],
                    sourceLetterIndex: 1, rules: ['madd_lazim'], shareGroup: null,
                },
            ],
            [0, 1, 2, 3],
        );
        const { container } = mount([word], intervals);
        // The maddah folds onto its letter — one لٓ cell, not a bare ٓ beside it.
        const letters = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .map((e) => e.textContent);
        expect(letters).toEqual(['ا', 'لٓ']);
        const carrier = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .find((e) => e.textContent === 'لٓ')!;
        expect(carrier.style.boxShadow).not.toBe('');
        // The letter takes the FIRST colourable rule the producer listed.
        expect(carrier.style.boxShadow).toContain('idgham-shafawi');
        // Per-phoneme: the long vowel is the maddah cell's, the rest the letter's.
        const ph = (i: number) => container.querySelector<HTMLElement>(`.mega-phoneme[data-index="${i}"]`)!;
        expect(ph(2).style.boxShadow).toContain('madd-lazim');
        expect(ph(3).style.boxShadow).toContain('idgham-shafawi');
        // The merged nasal hue is DISTINCT from the long-vowel madd hue.
        expect(ph(3).style.boxShadow).not.toBe(ph(2).style.boxShadow);
    });

    it('muqattaat: a default-off rule leaves its cells bare until enabled (طه)', () => {
        // طه = ṭā · hā, two 2-count letters. ط is istiʿlāʾ → tafkheem + madd ṭabīʿī;
        // ه is light → madd ṭabīʿī alone, which is off by default.
        const intervals: PhonemeInterval[] = [
            { phone: 'tˤ', start: 0, end: 0.2 }, { phone: 'aˤ:', start: 0.2, end: 0.7 },
            { phone: 'h', start: 0.7, end: 0.8 }, { phone: 'a:', start: 0.8, end: 1.2 },
        ];
        const word = w(
            [{ char: 'ط', start: 0, end: 0.7, silent: false }, { char: 'ه', start: 0.7, end: 1.2, silent: false }],
            [
                { chars: 'ط', role: 'base', status: 'present', phonemeIndices: [0, 1], sourceLetterIndex: 0, rules: ['madd_tabii', 'tafkheem'], shareGroup: null },
                { chars: 'ه', role: 'base', status: 'present', phonemeIndices: [2, 3], sourceLetterIndex: 1, rules: ['madd_tabii'], shareGroup: null },
            ],
            [0, 1, 2, 3],
        );
        const letter = (c: HTMLElement, ch: string) =>
            Array.from(c.querySelectorAll<HTMLElement>('.mega-letter')).find((e) => e.textContent === ch)!;
        // madd ṭabīʿī off: ط keeps only its tafkheem bar, ه draws nothing.
        const off = mount([word], intervals).container;
        expect(letter(off, 'ط').style.boxShadow).toContain('tafkheem');
        expect(letter(off, 'ط').style.boxShadow).not.toContain('madd');
        expect(letter(off, 'ه').style.boxShadow).toBe('');
        cleanup();
        // madd ṭabīʿī on: the 2-count bar appears under the tafkheem bar on ط, and
        // alone on ه.
        setRuleEnabled('madd_tabii', true);
        const on = mount([word], intervals).container;
        expect(letter(on, 'ط').style.boxShadow).toContain('madd-tabii');
        expect(letter(on, 'ط').style.boxShadow).toContain('tafkheem');
        expect(letter(on, 'ه').style.boxShadow).toContain('madd-tabii');
        expect(letter(on, 'ه').style.boxShadow).not.toContain('tafkheem');
    });

    it('muqattaat qalqala on a consonant rides its render-only Q echo, not the consonant', () => {
        const iv: PhonemeInterval[] = [
            { phone: 'd', start: 0, end: 0.1 }, { phone: 'Q', start: 0.1, end: 0.15 },
        ];
        const word = w(
            [{ char: 'دٓ', start: 0, end: 0.15, silent: false }],
            [
                {
                    chars: 'دٓ', role: 'base', status: 'present', phonemeIndices: [0],
                    sourceLetterIndex: 0, rules: ['qalqala_kubra'], shareGroup: null,
                },
            ],
            [0, 1], // the consonant + its render-only Q echo
        );
        const { container } = mount([word], iv);
        const ph = (i: number) => container.querySelector<HTMLElement>(`.mega-phoneme[data-index="${i}"]`);
        // qalqala kubrā renders as the side-wrap ::after (the --tj-kubra var + class),
        // not a box-shadow bar
        expect(ph(0)!.classList.contains('tj-kubra')).toBe(false);            // consonant bare
        expect(ph(1)!.classList.contains('tj-kubra')).toBe(true);            // Q echo carries the bracket
        expect(ph(1)!.style.getPropertyValue('--tj-kubra')).toContain('qalqala');
    });

    it('muqattaat with no haraka cells (عٓسٓقٓ-style) renders every letter + its underline', () => {
        // عٓسٓقٓ carries no ḥaraka at all — every letter is a `base` cell followed by
        // its maddah. They must render through the main per-cell path (letter glyph +
        // its underline + phonemes under their own cell), NOT the synthetic fallback.
        const intervals: PhonemeInterval[] = [
            { phone: 'ʕ', start: 0, end: 0.1 }, { phone: 'a', start: 0.1, end: 0.15 },
            { phone: 'j', start: 0.15, end: 0.5 }, { phone: 'ŋ', start: 0.5, end: 0.8 },
            { phone: 's', start: 0.8, end: 0.9 }, { phone: 'i:', start: 0.9, end: 1.3 },
            { phone: 'ŋˤ', start: 1.3, end: 1.6 }, { phone: 'q', start: 1.6, end: 1.7 },
        ];
        const word = w(
            [
                { char: 'عٓ', start: 0, end: 0.8, silent: false },
                { char: 'سٓ', start: 0.8, end: 1.6, silent: false },
                { char: 'قٓ', start: 1.6, end: 1.7, silent: false },
            ],
            [
                { chars: 'ع', role: 'base', status: 'present', phonemeIndices: [0, 1, 2, 3], sourceLetterIndex: 0, rules: ['ikhfaa'], shareGroup: null },
                { chars: 'ٓ', role: 'madd', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 0, rules: ['orthographic_silence'], shareGroup: null },
                { chars: 'س', role: 'base', status: 'present', phonemeIndices: [4, 5, 6], sourceLetterIndex: 1, rules: ['ikhfaa', 'madd_lazim'], shareGroup: null },
                { chars: 'ٓ', role: 'madd', status: 'present', phonemeIndices: [5], sourceLetterIndex: 1, rules: ['madd_lazim'], shareGroup: null },
                { chars: 'ق', role: 'base', status: 'present', phonemeIndices: [7], sourceLetterIndex: 2, rules: ['madd_lazim', 'tafkheem'], shareGroup: null },
                { chars: 'ٓ', role: 'madd', status: 'present', phonemeIndices: [7], sourceLetterIndex: 2, rules: ['madd_lazim', 'tafkheem'], shareGroup: null },
            ],
            [0, 1, 2, 3, 4, 5, 6, 7],
        );
        const { container } = mount([word], intervals);
        const letters = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'));
        // Three letters, each with its maddah folded on — no bare ٓ cell.
        expect(letters.map((e) => e.textContent)).toEqual(['عٓ', 'سٓ', 'قٓ']);
        const letter = (ch: string) => letters.find((e) => e.textContent === ch)!;
        expect(letter('عٓ').style.boxShadow).toContain('ikhfaa');
        expect(letter('سٓ').style.boxShadow).toContain('ikhfaa');
        expect(letter('قٓ').style.boxShadow).toContain('madd-lazim');
        // Per-phoneme: سٓ's long vowel takes the maddah cell's madd, its nasal the
        // letter's ikhfaa.
        const ph = (i: number) => container.querySelector<HTMLElement>(`.mega-phoneme[data-index="${i}"]`)!;
        expect(ph(5).style.boxShadow).toContain('madd-lazim');
        expect(ph(6).style.boxShadow).toContain('ikhfaa');
    });

    it('a heavy ikhfaa nasal stacks tafkheem on the letter that fired both rules', () => {
        // An ikhfaa hum before a heavy istiʿlāʾ letter is heavy, and the producer
        // names both rules on the letter. The bar comes from the rules, so it
        // draws whichever nasal token the shard happens to store.
        const build = (nasal: string) => {
            const intervals: PhonemeInterval[] = [
                { phone: 's', start: 0, end: 0.1 }, { phone: 'i:', start: 0.1, end: 0.5 },
                { phone: nasal, start: 0.5, end: 0.8 }, { phone: 'q', start: 0.8, end: 0.9 },
            ];
            const word = w(
                [{ char: 'سٓ', start: 0, end: 0.8, silent: false }, { char: 'قٓ', start: 0.8, end: 0.9, silent: false }],
                [
                    { chars: 'س', role: 'base', status: 'present', phonemeIndices: [0, 1, 2], sourceLetterIndex: 0, rules: ['ikhfaa', 'tafkheem', 'madd_lazim'], shareGroup: null },
                    { chars: 'ٓ', role: 'madd', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: ['madd_lazim'], shareGroup: null },
                    { chars: 'ق', role: 'base', status: 'present', phonemeIndices: [3], sourceLetterIndex: 1, rules: ['tafkheem'], shareGroup: null },
                ],
                [0, 1, 2, 3],
            );
            return mount([word], intervals).container;
        };
        for (const nasal of ['ŋ', 'ŋˤ']) {
            const c = build(nasal);
            const nasalBox = c.querySelector<HTMLElement>('.mega-phoneme[data-index="2"]')!;
            expect(nasalBox.style.boxShadow).toContain('ikhfaa');
            expect(nasalBox.style.boxShadow).toContain('tafkheem');
            cleanup();
        }
    });

    // --- Special rules (the full-cell border channel) -----------------------

    it('imala rings the whole cell instead of underlining it (مَجْر۪ىهَا)', () => {
        // ر۪ + ى sound one imāla vowel eː. Both cells carry [madd_tabii, imala]; madd
        // ṭabīʿī is off by default, so the ring is all that shows — and it draws as a
        // full inset border, not a bottom bar.
        const intervals: PhonemeInterval[] = [
            { phone: 'r', start: 0, end: 0.1 }, { phone: 'e:', start: 0.1, end: 0.6 },
        ];
        const word = w(
            [{ char: 'ر۪', start: 0, end: 0.1, silent: false }, { char: 'ى', start: 0.1, end: 0.6, silent: false }],
            [
                { chars: 'ر۪', role: 'base', status: 'present', phonemeIndices: [0], sourceLetterIndex: 0, rules: ['madd_tabii', 'imala'], shareGroup: null },
                { chars: 'ى', role: 'madd', status: 'present', phonemeIndices: [1], sourceLetterIndex: 1, rules: ['madd_tabii', 'imala'], shareGroup: null },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        const raa = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'))
            .find((e) => e.textContent === 'ر۪')!;
        expect(raa.style.boxShadow).toBe('inset 0 0 0 2px var(--tj-special)');
        // the eː phoneme rings too
        const vowel = container.querySelector<HTMLElement>('.mega-phoneme[data-index="1"]')!;
        expect(vowel.style.boxShadow).toBe('inset 0 0 0 2px var(--tj-special)');
        // ...and the ring survives beside a bar once the madd is switched on
        cleanup();
        setRuleEnabled('madd_tabii', true);
        const on = mount([word], intervals).container;
        const raaOn = Array.from(on.querySelectorAll<HTMLElement>('.mega-letter'))
            .find((e) => e.textContent === 'ر۪')!;
        expect(raaOn.style.boxShadow).toBe(
            'inset 0 -2px 0 var(--tj-madd-tabii), inset 0 0 0 2px var(--tj-special)',
        );
    });

    it('tashil / ishmam / ibdal al-hamzah all ring their cell under one toggle', () => {
        const ring = (rules: string[], chars: string) => {
            const intervals: PhonemeInterval[] = [{ phone: 'x', start: 0, end: 0.2 }];
            const word = w(
                [{ char: chars, start: 0, end: 0.2, silent: false }],
                [{ chars, role: 'base', status: 'present', phonemeIndices: [0], sourceLetterIndex: 0, rules, shareGroup: null }],
                [0],
            );
            const c = mount([word], intervals).container;
            const box = Array.from(c.querySelectorAll<HTMLElement>('.mega-letter'))
                .find((e) => e.textContent === chars)!.style.boxShadow;
            cleanup();
            return box;
        };
        expect(ring(['tashil'], 'ا۬')).toBe('inset 0 0 0 2px var(--tj-special)');
        expect(ring(['ishmam'], 'م')).toBe('inset 0 0 0 2px var(--tj-special)');
        expect(ring(['ibdal_hamza'], 'ئ')).toBe('inset 0 0 0 2px var(--tj-special)');
        setRuleEnabled('special', false);
        expect(ring(['tashil'], 'ا۬')).toBe('');
    });

    // --- Cross-word merger carrier timing (idgham / shafawi) ----------------

    it('cross-word idgham carrier: letter span = the ghunnah nasal, highlight = the haraka+ghunnah union', () => {
        // tanwīn → mīm idgham-with-ghunnah (هُدًى مِّن). The source tanwīn sounds
        // [haraka, ghunnah]; the receiving merged mīm sounds ONLY the ghunnah. The
        // carrier's own click/loop/tooltip span must be the nasal alone, while its
        // highlight band still co-lights the whole haraka+ghunnah union.
        const intervals: PhonemeInterval[] = [
            { phone: 'd', start: 0, end: 0.1 }, // word1 consonant
            { phone: 'a', start: 0.1, end: 0.22 }, // tanwīn fatḥatān vowel (source haraka)
            { phone: 'm̃', start: 0.22, end: 0.88 }, // merged ghunnah mīm (carrier nasal)
        ];
        const src = w(
            [{ char: 'د', start: 0, end: 0.22, silent: false }],
            [
                base(0, [0], { chars: 'د' }),
                { chars: 'ً', role: 'tanween', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: ['idgham_bi_ghunnah'], shareGroup: 4 },
            ],
            [0, 1],
        );
        const carrier = { ...w(
            [{ char: 'م', start: 0.22, end: 0.88, silent: false }],
            [{ chars: 'مّ', role: 'base', status: 'present', phonemeIndices: [2], sourceLetterIndex: 0, rules: [], shareGroup: 4 }],
            [2],
        ), location: '1:2:2' };
        const { container } = mount([src, carrier], intervals);
        const meem = container.querySelector<HTMLElement>('.mega-letter[data-word-index="1"]')!;
        // Letter (click/loop/tooltip) = the ghunnah nasal alone [0.22, 0.88] = 660ms.
        expect(meem.dataset.letterStart).toBe('0.22');
        expect(meem.dataset.letterEnd).toBe('0.88');
        // Highlight band still spans the whole merger [0.1, 0.88] (haraka + ghunnah).
        expect(meem.dataset.cellStart).toBe('0.1');
        expect(meem.dataset.cellEnd).toBe('0.88');
        // The source tanwīn keeps haraka + ghunnah (the union) — carrier time + haraka time.
        const tanwin = container.querySelector<HTMLElement>('.haraka-cell[data-cell-timed]')!;
        expect(tanwin.dataset.cellStart).toBe('0.1');
        expect(tanwin.dataset.cellEnd).toBe('0.88');
    });

    it('idgham shafawi: both meems take the same single ghunnah nasal as their letter span', () => {
        // قُلُوبِهِم مَّرَضٌ — the two meems fuse into ONE held nasal m̃ (stored on the
        // source meem); the receiving meem owns only the trailing vowel. Per the
        // merger model both meems read the SAME nasal duration as their own span,
        // not the union and not the stray vowel.
        const intervals: PhonemeInterval[] = [
            { phone: 'm̃', start: 0, end: 0.59 }, // the one merged nasal (on the source meem)
            { phone: 'a', start: 0.59, end: 0.66 }, // the receiving word's first vowel
        ];
        const src = w(
            [{ char: 'م', start: 0, end: 0.59, silent: false }],
            [{ chars: 'م', role: 'base', status: 'present', phonemeIndices: [0], sourceLetterIndex: 0, rules: ['idgham_shafawi'], shareGroup: 3 }],
            [0],
        );
        const recv = { ...w(
            [{ char: 'م', start: 0.59, end: 0.66, silent: false }],
            [{ chars: 'م', role: 'base', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: 3 }],
            [1],
        ), location: '1:2:2' };
        const { container } = mount([src, recv], intervals);
        const srcMeem = container.querySelector<HTMLElement>('.mega-letter[data-word-index="0"]')!;
        const recvMeem = container.querySelector<HTMLElement>('.mega-letter[data-word-index="1"]')!;
        // Both meems' letter (click/loop/tooltip) span = the single nasal [0, 0.59] = 590ms.
        for (const m of [srcMeem, recvMeem]) {
            expect(m.dataset.letterStart).toBe('0');
            expect(m.dataset.letterEnd).toBe('0.59');
        }
        // Highlight spans the union [0, 0.66] for both (co-light cue unchanged).
        for (const m of [srcMeem, recvMeem]) {
            expect(m.dataset.cellStart).toBe('0');
            expect(m.dataset.cellEnd).toBe('0.66');
        }
    });
});

/**
 * Per-grapheme phoneme alignment: each cell-group is a mini-grid where every
 * phoneme sits under its OWN source grapheme — the consonant under the base
 * letter, the vowel under its diacritic. A silent letter or a merged-away
 * consonant leaves its column with no phoneme; a long vowel's sound sits under
 * its diacritic, not the carrier.
 */
describe('UnifiedDisplay — per-grapheme phoneme alignment', () => {
    beforeEach(() => {
        dashPort.attachElement(
            makePortAudioStub({ src: 'http://audio/1.mp3', readyState: 4 }) as unknown as HTMLAudioElement,
        );
        dashPort.setSource({ audioUrl: 'http://audio/1.mp3', reciter: null, vbr: false });
    });
    afterEach(() => {
        cleanup();
        resetAllTajweed(); // izhar / madd-ṭabīʿī default off — undo any per-test enable
        loadedVerse.set(null);
        dashPort.attachElement(null);
    });

    const clusterPhones = (el: HTMLElement): (string | null)[] =>
        Array.from(el.querySelectorAll('.ph-base')).map((p) => p.textContent);

    /** Map a cell-group's grid columns → { grapheme glyph, phonemes } by reading
     *  the inline `grid-column` each cell/cluster is placed at. */
    const colsOf = (group: HTMLElement) => {
        const startCol = (el: HTMLElement): number =>
            parseInt((el.style.gridColumn || '0').split('/')[0]!.trim(), 10);
        const graphemes = new Map<number, string>();
        group.querySelectorAll<HTMLElement>(':scope > .mega-letter').forEach((l) =>
            graphemes.set(startCol(l), l.textContent ?? ''));
        group.querySelectorAll<HTMLElement>(':scope > .dia-track').forEach((d) =>
            graphemes.set(startCol(d), d.querySelector('.g')?.textContent ?? ''));
        const phon = new Map<number, (string | null)[]>();
        group.querySelectorAll<HTMLElement>(':scope > .phoneme-cluster').forEach((c) =>
            phon.set(startCol(c), Array.from(c.querySelectorAll('.ph-base')).map((p) => p.textContent)));
        return { graphemes, phon };
    };

    it('و/ى waqf carrier: ḍamma+waw share uː; the carrier’s own fatḥa drops AFTER it, silent', () => {
        // هُوَ stopped on → /huː/: the waw turns madd_ʿāriḍ (its /w/ becomes the
        // prolongation of the preceding ḍamma) and its OWN fatḥa drops. The vowel
        // unit is double-sided — [ḍamma, waw, silent fatḥa] — with uː spanning only
        // [ḍamma, waw]; the haa stands alone, the trailing fatḥa sits past the waw,
        // silent (no phoneme, not cell-timed).
        const intervals: PhonemeInterval[] = [
            { phone: 'h', start: 0, end: 0.3 },
            { phone: 'u:', start: 0.3, end: 1.0 },
        ];
        const word = w(
            [{ char: 'ه', start: 0, end: 0.3, silent: false }, { char: 'و', start: 0.3, end: 1.0, silent: false }],
            [
                base(0, [0], { chars: 'ه' }),
                { chars: 'ُ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: 0 },
                { chars: 'و', role: 'madd', status: 'present', phonemeIndices: [1], sourceLetterIndex: 1, rules: ['madd_arid_lil_sukun'], shareGroup: 0 },
                { chars: 'َ', role: 'haraka', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 1, rules: [], shareGroup: null },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        const groups = container.querySelectorAll<HTMLElement>('.cell-group');
        expect(groups.length).toBe(2);
        // The haa stands alone (its dropped neighbour does NOT land on it).
        expect(Array.from(groups[0]!.querySelectorAll('.mega-letter')).map((l) => l.textContent)).toEqual(['ه']);
        // The vowel group is double-sided: ḍamma (col 1), waw carrier (col 2), the
        // carrier's silent fatḥa AFTER it (col 3).
        const vowel = groups[1]!;
        const glyphCol = (glyph: string) =>
            Array.from(vowel.querySelectorAll<HTMLElement>('.dia-track, .mega-letter'))
                .find((e) => (e.querySelector('.g') ?? e).textContent?.trim() === glyph)?.style.gridColumn;
        expect(glyphCol('ُ')).toBe('1');
        expect(glyphCol('و')).toBe('2');
        expect(glyphCol('َ')).toBe('3');
        // uː spans [ḍamma, waw] only — the silent fatḥa is past the span.
        const cluster = vowel.querySelector<HTMLElement>('.phoneme-cluster')!;
        expect(cluster.querySelector('.ph-base')!.textContent).toBe('u');
        expect(cluster.style.gridColumn).toBe('1 / span 2');
        // The trailing fatḥa is silent (dropped — not cell-timed).
        const fatha = Array.from(vowel.querySelectorAll<HTMLElement>('.haraka-cell'))
            .find((s) => s.querySelector('.g')?.textContent === 'َ')!;
        expect(fatha.hasAttribute('data-cell-timed')).toBe(false);
    });

    it('places the consonant under its letter and the short vowel under its mark (قُلْ)', () => {
        // ق+ḍamma → q under ق, u under the ḍamma; ل+sukūn → l under ل.
        const intervals: PhonemeInterval[] = [
            { phone: 'q', start: 0, end: 0.1 }, { phone: 'u', start: 0.1, end: 0.2 },
            { phone: 'l', start: 0.2, end: 0.3 },
        ];
        const word = w(
            [{ char: 'ق', start: 0, end: 0.2, silent: false }, { char: 'ل', start: 0.2, end: 0.3, silent: false }],
            [
                base(0, [0]),
                { chars: 'ُ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
                base(1, [2]),
                { chars: 'ْ', role: 'haraka', status: 'present', phonemeIndices: [], sourceLetterIndex: 1, rules: [], shareGroup: null }, // sukūn
            ],
            [0, 1, 2],
        );
        const { container } = mount([word], intervals);
        const groups = container.querySelectorAll<HTMLElement>('.cell-group');
        expect(groups.length).toBe(2);
        // ق group: TWO grapheme columns — ق (col 1) → q, ḍamma (col 2) → u.
        expect(groups[0]!.style.getPropertyValue('--gcols')).toBe('2');
        const qg = colsOf(groups[0]!);
        expect(qg.graphemes.get(1)).toBe('ق');
        expect(qg.phon.get(1)).toEqual(['q']);
        expect(qg.phon.get(2)).toEqual(['u']);
        // ل group: l under ل.
        expect(colsOf(groups[1]!).phon.get(1)).toEqual(['l']);
    });

    it('leaves a silent base letter\'s column with no phoneme', () => {
        // ٱل : hamza-waṣl ٱ is silent (dropped, no phoneme); ل sounds [l]. ٱ's column
        // has NO phoneme cluster — a reserved empty slot.
        const intervals: PhonemeInterval[] = [{ phone: 'l', start: 0.1, end: 0.3 }];
        const word = w(
            [{ char: 'ٱ', start: null, end: null, silent: true }, { char: 'ل', start: 0.1, end: 0.3, silent: false }],
            [base(0, [], { status: 'dropped', chars: 'ٱ' }), base(1, [0], { chars: 'ل' })],
            [0],
        );
        const { container } = mount([word], intervals);
        const groups = container.querySelectorAll<HTMLElement>('.cell-group');
        // ٱ group: grapheme present, but no phoneme cluster at all.
        expect(colsOf(groups[0]!).graphemes.get(1)).toBe('ٱ');
        expect(groups[0]!.querySelectorAll('.phoneme-cluster').length).toBe(0);
        // ل group: l under ل.
        expect(colsOf(groups[1]!).phon.get(1)).toEqual(['l']);
    });

    it('a dropped tanwīn at waqf gets no phoneme — only the consonant sounds', () => {
        // مٌ at waqf: م sounds [m] under its column; the ḍammatan is dropped — its
        // (col 2) has no phoneme, and the mark is greyed in the letter row.
        const intervals: PhonemeInterval[] = [{ phone: 'm', start: 0, end: 0.2 }];
        const word = w(
            [{ char: 'م', start: 0, end: 0.2, silent: false }],
            [
                base(0, [0]),
                { chars: 'ٌ', role: 'tanween', status: 'dropped', phonemeIndices: [], sourceLetterIndex: 0, rules: [], shareGroup: null },
            ],
            [0],
        );
        const { container } = mount([word], intervals);
        const group = container.querySelector<HTMLElement>('.cell-group')!;
        const { phon } = colsOf(group);
        expect(phon.get(1)).toEqual(['m']); // م
        // only ONE cluster (under م) — the dropped tanwīn column has none.
        expect(group.querySelectorAll('.phoneme-cluster').length).toBe(1);
        expect(container.querySelector('.haraka-cell.dia-dropped')).toBeTruthy();
    });

    it('spans a long-vowel sound across its [diacritic, carrier] unit, centred', () => {
        // مِي : base م → [m]; the [kasra, ي] unit sounds one iː. The single phoneme
        // SPANS both grapheme columns (grid-column 1 / span 2) and centres across the
        // unit, rather than pinning under one sub-column.
        const intervals: PhonemeInterval[] = [
            { phone: 'm', start: 0, end: 0.1 }, { phone: 'i:', start: 0.1, end: 0.4 },
        ];
        const word = w(
            [{ char: 'م', start: 0, end: 0.1, silent: false }, { char: 'ي', start: 0.1, end: 0.4, silent: false }],
            [
                base(0, [0]),
                { chars: 'ِ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: 1 },
                { chars: 'ي', role: 'madd', status: 'present', phonemeIndices: [1], sourceLetterIndex: 1, rules: [], shareGroup: 1 },
            ],
            [0, 1],
        );
        const { container } = mount([word], intervals);
        const groups = container.querySelectorAll<HTMLElement>('.cell-group');
        expect(groups.length).toBe(2);
        expect(colsOf(groups[0]!).phon.get(1)).toEqual(['m']); // base م
        // vowel unit [kasra (col 1), ي carrier (col 2)] — graphemes in both columns.
        const vg = groups[1]!;
        const cols = colsOf(vg);
        expect(cols.graphemes.get(1)).toBe('ِ');
        expect(cols.graphemes.get(2)).toBe('ي');
        // ONE cluster, spanning both columns (centred across the unit).
        const clusters = vg.querySelectorAll<HTMLElement>(':scope > .phoneme-cluster');
        expect(clusters.length).toBe(1);
        expect(clusters[0]!.style.gridColumn.replace(/\s+/g, ' ').trim()).toBe('1 / span 2');
        expect(Array.from(clusters[0]!.querySelectorAll('.ph-base')).map((p) => p.textContent)).toEqual(['i']);
    });

    it('the clusters partition the word’s phonemes — none dropped, none duplicated', () => {
        const intervals: PhonemeInterval[] = [
            { phone: 'q', start: 0, end: 0.1 }, { phone: 'u', start: 0.1, end: 0.2 },
            { phone: 'l', start: 0.2, end: 0.3 },
        ];
        const word = w(
            [{ char: 'ق', start: 0, end: 0.2, silent: false }, { char: 'ل', start: 0.2, end: 0.3, silent: false }],
            [
                base(0, [0]),
                { chars: 'ُ', role: 'haraka', status: 'present', phonemeIndices: [1], sourceLetterIndex: 0, rules: [], shareGroup: null },
                base(1, [2]),
            ],
            [0, 1, 2],
        );
        const { container } = mount([word], intervals);
        const all = Array.from(container.querySelectorAll<HTMLElement>('.phoneme-cluster .mega-phoneme'))
            .map((p) => p.querySelector('.ph-base')!.textContent);
        expect(all).toEqual(['q', 'u', 'l']); // exactly the word's three sounds, in order
    });

    it('a qalqala echo (Q, not cell-indexed) rides its consonant column, not the word end', () => {
        // قْد : ق sounds [q] then the qalqala echo [Q] (render-only — in NO cell's
        // phonemeIndices), then د [d]. Q must sit in the ق column beside q, NOT jump
        // to the last cluster (the regression this guards).
        const intervals: PhonemeInterval[] = [
            { phone: 'q', start: 0, end: 0.1 },
            { phone: 'Q', start: 0.1, end: 0.15 },
            { phone: 'd', start: 0.15, end: 0.3 },
        ];
        const word = w(
            [{ char: 'ق', start: 0, end: 0.15, silent: false }, { char: 'د', start: 0.15, end: 0.3, silent: false }],
            [
                base(0, [0], { rules: ['qalqala_sughra'] }), // ق owns only q (idx 0), not the Q echo
                { chars: 'ْ', role: 'haraka', status: 'present', phonemeIndices: [], sourceLetterIndex: 0, rules: [], shareGroup: null }, // sukūn
                base(1, [2]), // د owns d (idx 2)
            ],
            [0, 1, 2], // Q (idx 1) is rendered but indexed by no cell
        );
        const { container } = mount([word], intervals);
        const clusters = container.querySelectorAll<HTMLElement>('.phoneme-cluster');
        expect(clusters.length).toBe(2);
        expect(clusterPhones(clusters[0]!)).toEqual(['q', 'Q']); // echo rides its qāf
        expect(clusterPhones(clusters[1]!)).toEqual(['d']);
    });

    it('heavy ikhfaa: the nasal before an istiʿlāʾ letter stacks tafkheem above the ikhfaa bar', () => {
        // نْ before ص: the producer names the hum heavy and spends a character on
        // it (ŋˤ), so the noon cell carries both rules and stacks both bars.
        const iv: PhonemeInterval[] = [
            { phone: 'ŋˤ', start: 0, end: 0.15 },
            { phone: 'sˤ', start: 0.15, end: 0.4 },
        ];
        const word = w(
            [{ char: 'ن', start: 0, end: 0.15, silent: false }, { char: 'ص', start: 0.15, end: 0.4, silent: false }],
            [
                base(0, [0], { chars: 'ن', rules: ['ikhfaa', 'tafkheem'] }),
                base(1, [1], { chars: 'ص', rules: ['tafkheem'] }),
            ],
            [0, 1],
        );
        const { container } = mount([word], iv);
        const noon = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter')).find((e) => e.textContent === 'ن')!;
        expect(noon.style.boxShadow).toContain('var(--tj-ikhfaa)');
        expect(noon.style.boxShadow).toContain('var(--tj-tafkheem)');
        // the nasal phoneme cell stacks the same two bars (ikhfaa below, tafkheem above)
        const nasal = container.querySelector<HTMLElement>('.mega-phoneme[data-index="0"]')!;
        expect(nasal.style.boxShadow).toContain('var(--tj-ikhfaa)');
        expect(nasal.style.boxShadow.indexOf('ikhfaa')).toBeLessThan(nasal.style.boxShadow.indexOf('tafkheem'));
    });

    it('a LIGHT ikhfaa (nasal before a non-istiʿlāʾ letter) gets no tafkheem bar', () => {
        const iv: PhonemeInterval[] = [
            { phone: 'ŋ', start: 0, end: 0.15 },
            { phone: 't', start: 0.15, end: 0.4 },
        ];
        const word = w(
            [{ char: 'ن', start: 0, end: 0.15, silent: false }, { char: 'ت', start: 0.15, end: 0.4, silent: false }],
            [base(0, [0], { chars: 'ن', rules: ['ikhfaa'] }), base(1, [1], { chars: 'ت' })],
            [0, 1],
        );
        const { container } = mount([word], iv);
        const noon = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter')).find((e) => e.textContent === 'ن')!;
        expect(noon.style.boxShadow).toContain('var(--tj-ikhfaa)');
        expect(noon.style.boxShadow).not.toContain('tafkheem');
    });

    it('mutamathilayn un-greys + underlines its silent source (it co-lights via the share group)', () => {
        // قُل لَّا cross-word: the source ل is silent but shares the merger group, so it
        // reads visible + underlined (NOT greyed).
        const iv: PhonemeInterval[] = [{ phone: 'll', start: 0, end: 0.3 }];
        const src = w(
            [{ char: 'ل', start: 0, end: 0, silent: true }],
            [base(0, [], { chars: 'ل', rules: ['idgham_mutamathilayn'], shareGroup: 3 })],
            [],
        );
        const recv = w(
            [{ char: 'ل', start: 0, end: 0.3, silent: false }],
            [base(0, [0], { chars: 'ل', shareGroup: 3 })],
            [0],
        );
        const { container } = mount([src, recv], iv);
        const source = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter')).find((e) => e.textContent === 'ل')!;
        expect(source.classList.contains('silent')).toBe(false); // un-greyed (co-lit)
        expect(source.style.boxShadow).toContain('var(--tj-mutamathilayn)');
    });

    it('an idgham TARGET stacks the merge bar above its own ghunnah (ٱرْكَب مَّعَنَا → مّ)', () => {
        // the receiving mīm sounds ghunnah (its own rule) AND is the mutajānisayn target
        // (carried as a secondary `merge` tag): ghunnah bar below, mutajānisayn above.
        const iv: PhonemeInterval[] = [{ phone: 'm̃', start: 0, end: 0.3 }];
        const word = w(
            [{ char: 'م', start: 0, end: 0.3, silent: false }],
            [base(0, [0], { chars: 'مّ', rules: ['ghunnah', 'idgham_mutajanisayn_kamil'] })],
            [0],
        );
        const { container } = mount([word], iv);
        const meem = container.querySelector<HTMLElement>('.mega-letter:not(.implicit)')!;
        const s = meem.style.boxShadow;
        expect(s).toContain('var(--tj-ghunnah)');
        expect(s).toContain('var(--tj-mutajanisayn)');
        expect(s.indexOf('ghunnah')).toBeLessThan(s.indexOf('mutajanisayn')); // ghunnah below the merge
    });

    it('within-word naqis (بَسَطتَ): BOTH letters AND both phonemes underline; tafkheem rides only the heavy ط/tˤ', () => {
        // ط (source) and ت (target) both SOUND (nāqiṣ). The merge underline + tooltip
        // must land on both letters AND both phonemes; tafkhīm stacks only on the heavy
        // istiʿlāʾ ط and its tˤ phoneme. The tˤ phoneme is the regression: an idgham
        // (bridge-tag) source that still owns a phoneme must badge it.
        const iv: PhonemeInterval[] = [
            { phone: 'tˤ', start: 0, end: 0.15 }, { phone: 't', start: 0.15, end: 0.3 },
        ];
        const word = w(
            [{ char: 'ط', start: 0, end: 0.15, silent: false }, { char: 'ت', start: 0.15, end: 0.3, silent: false }],
            [
                base(0, [0], { chars: 'ط', rules: ['idgham_mutajanisayn_naqis', 'tafkheem'] }),
                base(1, [1], { chars: 'ت' , rules: ['idgham_mutajanisayn_naqis'] }),
            ],
            [0, 1],
        );
        const { container } = mount([word], iv);
        const letters = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'));
        const taa = letters.find((e) => e.textContent === 'ط')!; // source (heavy)
        const teh = letters.find((e) => e.textContent === 'ت')!; // target
        const ph = Array.from(container.querySelectorAll<HTMLElement>('.mega-phoneme'));
        // source ط letter + its tˤ phoneme: idgham + tafkheem
        expect(taa.style.boxShadow).toContain('var(--tj-mutajanisayn)');
        expect(taa.style.boxShadow).toContain('var(--tj-tafkheem)');
        expect(ph[0]!.style.boxShadow).toContain('var(--tj-mutajanisayn)');
        expect(ph[0]!.style.boxShadow).toContain('var(--tj-tafkheem)');
        // target ت letter + its t phoneme: idgham only, no tafkheem (light)
        expect(teh.style.boxShadow).toContain('var(--tj-mutajanisayn)');
        expect(teh.dataset.tjRules).toBe('Idgham Mutajanisayn Naqis');
        expect(ph[1]!.style.boxShadow).toContain('var(--tj-mutajanisayn)');
        expect(ph[1]!.style.boxShadow).not.toContain('var(--tj-tafkheem)');
    });

    it('mutamathilayn TARGET underlines via its secondary rules: [tag], source co-lights, bridge carries it (بَّيْنَكُمْ)', () => {
        // 2:282 وَلْيَكْتُب بَّيْنَكُمْ: source ب is co-lit (share group) + tagged; the receiver
        // بّ carries the rule as a SECONDARY tag (uniform with the other idghams), so the
        // target letter underlines without depending on the share-group path alone. The
        // merged bb is the bridge tile.
        const iv: PhonemeInterval[] = [{ phone: 'bb', start: 0, end: 0.3, bridge: 'idgham_mutamathilayn' }];
        const src = w(
            [{ char: 'ب', start: 0, end: 0, silent: true }],
            [base(0, [], { chars: 'ب', rules: ['idgham_mutamathilayn'], shareGroup: 0 })],
            [],
        );
        const recv = w(
            [{ char: 'ب', start: 0, end: 0.3, silent: false }],
            [base(0, [0], { chars: 'بّ', shareGroup: 0 , rules: ['idgham_mutamathilayn'] })],
            [0],
        );
        const { container } = mount([src, recv], iv);
        const letters = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'));
        const source = letters.find((e) => e.textContent === 'ب')!;
        const target = letters.find((e) => e.textContent === 'بّ')!;
        expect(source.classList.contains('silent')).toBe(false); // co-lit, not greyed
        expect(source.style.boxShadow).toContain('var(--tj-mutamathilayn)');
        expect(target.style.boxShadow).toContain('var(--tj-mutamathilayn)');
        expect(target.dataset.tjRules).toBe('Idgham Mutamathilayn');
        const bridge = container.querySelector<HTMLElement>('.crossword-bridge .mega-phoneme')!;
        expect(bridge.style.boxShadow).toContain('var(--tj-mutamathilayn)');
    });

    it('within-word mutaqaribayn (نَخْلُقكُّم): silent heavy ق underlines + tafkheem; sounding ك underlines, no tafkheem', () => {
        // قك inside one word: the heavy ق is the silent source (tafkhīm rides it), ك is the
        // sounding target. The target was previously untagged within a word — now it gets
        // the rule via its secondary tag (letter + phoneme).
        const iv: PhonemeInterval[] = [{ phone: 'kk', start: 0, end: 0.3 }];
        const word = w(
            [{ char: 'ق', start: 0, end: 0, silent: true }, { char: 'ك', start: 0, end: 0.3, silent: false }],
            [
                base(0, [], { chars: 'ق', rules: ['idgham_mutaqaribayn', 'tafkheem'] }),
                base(1, [0], { chars: 'كّ' , rules: ['idgham_mutaqaribayn'] }),
            ],
            [0],
        );
        const { container } = mount([word], iv);
        const letters = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter'));
        const qaf = letters.find((e) => e.textContent === 'ق')!;
        const kaf = letters.find((e) => e.textContent === 'كّ')!;
        expect(qaf.classList.contains('silent')).toBe(true); // silent source (no co-light)
        expect(qaf.style.boxShadow).toContain('var(--tj-mutaqaribayn)');
        expect(qaf.style.boxShadow).toContain('var(--tj-tafkheem)');
        expect(kaf.style.boxShadow).toContain('var(--tj-mutaqaribayn)');
        expect(kaf.style.boxShadow).not.toContain('var(--tj-tafkheem)'); // ك is light
        expect(container.querySelector<HTMLElement>('.mega-phoneme')!.style.boxShadow).toContain('var(--tj-mutaqaribayn)');
    });

    it('mutaqaribayn keeps its source SILENT but still underlines + names it (no co-light)', () => {
        // قُل رَّبِّ cross-word: the source ل does NOT co-light (no share group) → it stays
        // greyed, yet still draws its underline + tooltip.
        const iv: PhonemeInterval[] = [{ phone: 'rˤrˤ', start: 0, end: 0.3 }];
        const src = w(
            [{ char: 'ل', start: 0, end: 0, silent: true }],
            [base(0, [], { chars: 'ل', rules: ['idgham_mutaqaribayn'], shareGroup: null })],
            [],
        );
        const recv = w(
            [{ char: 'ر', start: 0, end: 0.3, silent: false }],
            [base(0, [0], { chars: 'ر' })],
            [0],
        );
        const { container } = mount([src, recv], iv);
        const source = Array.from(container.querySelectorAll<HTMLElement>('.mega-letter')).find((e) => e.textContent === 'ل')!;
        expect(source.classList.contains('silent')).toBe(true); // stays greyed (not co-lit)
        expect(source.style.boxShadow).toContain('var(--tj-mutaqaribayn)'); // but still underlined
        expect(source.dataset.tjRules).toBe('Idgham Mutaqaribayn'); // and named on hover
    });
});
