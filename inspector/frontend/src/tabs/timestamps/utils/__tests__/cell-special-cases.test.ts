import { describe, expect, it } from 'vitest';
import type { TsCell } from '../../../../lib/types/ts-client';
import {
    foldRidingMarks,
    iqlabMiniMeem,
    iqlabNoonSilentBase,
    iqlabTanweenVowel,
    isIqlabCell,
} from '../cell-special-cases';
import { DAMMA, DAMMATAN, FATHA, FATHATAN, KASRA, KASRATAN, MADDAH, MEEM_HI, MEEM_LO } from '../tajweed-script';

const cell = (over: Partial<TsCell>): TsCell => ({
    chars: '',
    role: 'base',
    status: 'present',
    phonemeIndices: [],
    sourceLetterIndex: 0,
    rules: [],
    shareGroup: null,
    ...over,
});

describe('cell-special-cases — iqlab noon', () => {
    const noon = cell({ chars: 'ن', phonemeIndices: [2], rules: ['iqlab'], sourceLetterIndex: 1 });

    it('silent base surrenders the nasal phone + underline, keeps an Iqlab hover rule', () => {
        const silent = iqlabNoonSilentBase(noon);
        expect(silent.chars).toBe('ن'); // the glyph stays
        expect(silent.phonemeIndices).toEqual([]); // no own phone → renders silent
        // a silent-only rule: draws no badge (absent from COLOR_RULES) but names "Iqlab"
        expect(silent.rules).toEqual(['iqlab_silent_noon']);
        expect(silent.shareGroup).toBeNull();
    });

    it('mini-meem owns the nasal phone + the lone iqlab rule', () => {
        const meem = iqlabMiniMeem(noon);
        expect(meem.chars).toBe(MEEM_HI); // above-slot source glyph
        expect(meem.role).toBe('tanween');
        expect(meem.status).toBe('inserted');
        expect(meem.phonemeIndices).toEqual([2]); // the click/loop target span
        expect(meem.sourceLetterIndex).toBe(1);
        expect(meem.rules).toEqual(['iqlab']); // the iqlab underline rides here
    });
});

describe('cell-special-cases — iqlab tanween', () => {
    const tanween = (mark: string): TsCell =>
        cell({ chars: mark, role: 'tanween', phonemeIndices: [4, 5], rules: ['iqlab'], sourceLetterIndex: 2 });

    it('splits into the single written haraka and the mini-meem that sounds the nasal', () => {
        const vowel = iqlabTanweenVowel(tanween(FATHATAN));
        expect(vowel.chars).toBe(FATHA); // the mushaf writes ONE mark, not the doubled one
        expect(vowel.role).toBe('haraka');
        expect(vowel.phonemeIndices).toEqual([4]); // keeps only the vowel
        expect(vowel.rules).toEqual([]); // the underline rides the meem alone

        const meem = iqlabMiniMeem(tanween(FATHATAN));
        expect(meem.chars).toBe(MEEM_HI);
        expect(meem.phonemeIndices).toEqual([5]); // the nasal
        expect(meem.rules).toEqual(['iqlab']);
    });

    it('picks the mini-meem slot from the vowel quality (fatha/damma high, kasra low)', () => {
        expect(iqlabMiniMeem(tanween(FATHATAN)).chars).toBe(MEEM_HI);
        expect(iqlabMiniMeem(tanween(DAMMATAN)).chars).toBe(MEEM_HI);
        expect(iqlabMiniMeem(tanween(KASRATAN)).chars).toBe(MEEM_LO);
        expect(iqlabTanweenVowel(tanween(DAMMATAN)).chars).toBe(DAMMA);
        expect(iqlabTanweenVowel(tanween(KASRATAN)).chars).toBe(KASRA);
    });

    it('recognises both iqlab origins and nothing else', () => {
        expect(isIqlabCell(cell({ chars: 'ن', rules: ['iqlab'], phonemeIndices: [2] }))).toBe(true);
        expect(isIqlabCell(tanween(FATHATAN))).toBe(true);
        // a tanwīn with only its vowel stored has no nasal to hand over
        expect(isIqlabCell(cell({ chars: FATHATAN, role: 'tanween', rules: ['iqlab'], phonemeIndices: [4] }))).toBe(false);
        expect(isIqlabCell(cell({ chars: 'ن', rules: ['ikhfaa'], phonemeIndices: [2] }))).toBe(false);
    });
});

describe('cell-special-cases — riding marks', () => {
    it('folds a lone maddah onto the letter before it, merging phones + rules', () => {
        const cells: TsCell[] = [
            cell({ chars: 'ا', role: 'madd', phonemeIndices: [1], rules: ['madd_tabii'], sourceLetterIndex: 1 }),
            cell({ chars: MADDAH, role: 'madd', phonemeIndices: [1], rules: ['madd_wajib_muttasil'], sourceLetterIndex: 1 }),
        ];
        const folded = foldRidingMarks(cells);
        expect(folded).toHaveLength(1);
        expect(folded[0]!.cell.chars).toBe('ا' + MADDAH);
        expect(folded[0]!.cell.rules).toEqual(['madd_tabii', 'madd_wajib_muttasil']);
        expect(folded[0]!.rawIndex).toBe(0); // the host keeps its own report index
    });

    it('leaves every other cell (and its raw index) alone', () => {
        const cells: TsCell[] = [
            cell({ chars: 'ه', sourceLetterIndex: 3 }),
            cell({ chars: 'ۥ', role: 'madd', status: 'dropped', sourceLetterIndex: 4 }),
            cell({ chars: MADDAH, role: 'madd', status: 'dropped', sourceLetterIndex: 4 }),
        ];
        const folded = foldRidingMarks(cells);
        expect(folded.map((f) => f.cell.chars)).toEqual(['ه', 'ۥ' + MADDAH]);
        expect(folded.map((f) => f.rawIndex)).toEqual([0, 1]);
    });
});
