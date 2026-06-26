import { describe, expect, it } from 'vitest';
import type { TsCell } from '../../../../lib/types/ts-client';
import {
    applyHamzaWaslMadd,
    iqlabNoonMiniMeem,
    iqlabNoonSilentBase,
    shedSilahMaddah,
    silahMaddahSources,
    wearSilahMaddah,
} from '../cell-special-cases';
import { MADDAH, MEEM_HI } from '../tajweed-script';

const cell = (over: Partial<TsCell>): TsCell => ({
    chars: '',
    role: 'base',
    status: 'present',
    phonemeIndices: [],
    sourceLetterIndex: 0,
    tag: null,
    shareGroup: null,
    ...over,
});

describe('cell-special-cases — iqlab noon', () => {
    const noon = cell({ chars: 'ن', phonemeIndices: [2], tag: 'iqlab_noon', sourceLetterIndex: 1 });

    it('silent base surrenders the nasal phone + underline, keeps an Iqlab hover tag', () => {
        const silent = iqlabNoonSilentBase(noon);
        expect(silent.chars).toBe('ن'); // the glyph stays
        expect(silent.phonemeIndices).toEqual([]); // no own phone → renders silent
        // a silent-only tag: draws no badge (absent from COLOR_RULES) but names "Iqlab"
        expect(silent.tag).toBe('iqlab_silent_noon');
        expect(silent.shareGroup).toBeNull();
    });

    it('mini-meem owns the nasal phone + the lone iqlab tag', () => {
        const meem = iqlabNoonMiniMeem(noon);
        expect(meem.chars).toBe(MEEM_HI); // above-slot source glyph
        expect(meem.role).toBe('tanween');
        expect(meem.status).toBe('inserted');
        expect(meem.phonemeIndices).toEqual([2]); // the click/loop target span
        expect(meem.sourceLetterIndex).toBe(1);
        expect(meem.tag).toBe('iqlab_noon'); // the iqlab underline rides here
    });
});

describe('cell-special-cases — silah madd', () => {
    it('detects a bearing letter with a maddah + a dropped silah carrier', () => {
        const cells: TsCell[] = [
            cell({ chars: 'ه' + MADDAH, role: 'base', sourceLetterIndex: 3 }),
            cell({ chars: 'ۥ', role: 'madd', status: 'dropped', sourceLetterIndex: 3 }),
        ];
        expect([...silahMaddahSources(cells, new Set([3]))]).toEqual([3]);
    });

    it('ignores a clean silah (no maddah merged onto the bearing letter)', () => {
        const cells: TsCell[] = [
            cell({ chars: 'ه', role: 'base', sourceLetterIndex: 3 }),
            cell({ chars: 'ۦ', role: 'madd', status: 'dropped', sourceLetterIndex: 3 }),
        ];
        expect(silahMaddahSources(cells, new Set([3])).size).toBe(0);
    });

    it('relocates the maddah glyph off the base onto the carrier', () => {
        expect(shedSilahMaddah('ه' + MADDAH)).toBe('ه');
        expect(wearSilahMaddah('ۥ')).toBe('ۥ' + MADDAH);
    });
});

describe('cell-special-cases — hamza-waṣl ibtidaa madd', () => {
    it('re-pairs the synthetic kasra + dropped ئ seat into one shared madd group', () => {
        const cells: TsCell[] = [
            cell({ chars: 'ٱ', phonemeIndices: [0], sourceLetterIndex: 0 }),
            cell({ chars: '', role: 'haraka', status: 'inserted', phonemeIndices: [1], tag: 'hamza_wasl_vowel', sourceLetterIndex: 0 }),
            cell({ chars: 'ئ', role: 'base', status: 'dropped', phonemeIndices: [], tag: 'silent_unclassified', sourceLetterIndex: 1 }),
            cell({ chars: 'ت', phonemeIndices: [2], sourceLetterIndex: 2 }),
        ];
        const out = applyHamzaWaslMadd(cells);
        // the synthetic kasra + the ئ seat now share a fresh group
        expect(out[1]!.shareGroup).not.toBeNull();
        expect(out[2]!.shareGroup).toBe(out[1]!.shareGroup);
        // the seat is re-cast as a co-lit madd carrier sounding the kasra's iː (no new phone)
        expect(out[2]!.role).toBe('madd');
        expect(out[2]!.status).toBe('present');
        expect(out[2]!.phonemeIndices).toEqual([1]);
        expect(out[2]!.tag).toBe('madd_tabii');
        // ٱ and ت are untouched
        expect(out[0]).toEqual(cells[0]);
        expect(out[3]).toEqual(cells[3]);
    });

    it('is a no-op for a normal hamza-waṣl (next base sounds, not a dropped seat)', () => {
        const cells: TsCell[] = [
            cell({ chars: 'ٱ', phonemeIndices: [0], sourceLetterIndex: 0 }),
            cell({ chars: '', role: 'haraka', status: 'inserted', phonemeIndices: [1], tag: 'hamza_wasl_vowel', sourceLetterIndex: 0 }),
            cell({ chars: 'ق', role: 'base', phonemeIndices: [2], sourceLetterIndex: 1 }),
        ];
        expect(applyHamzaWaslMadd(cells)).toBe(cells); // same reference — untouched
    });
});
