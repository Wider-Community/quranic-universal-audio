import { describe, expect, it } from 'vitest';
import type { TsCell } from '../../../../lib/types/ts-client';
import { cellWideRules } from '../cell-model';

const cell = (over: Partial<TsCell>): TsCell => ({
    chars: '', role: 'base', status: 'present', phonemeIndices: [],
    sourceLetterIndex: 0, rules: [], shareGroup: null, ...over,
});

describe('cellWideRules', () => {
    it('a tanween heavy on its fatha and clear on its noon draws neither whole (فِسْقًا)', () => {
        const c = cell({
            chars: 'ً', role: 'tanween', phonemeIndices: [4, 5],
            rules: ['izhar', 'tafkheem'],
            phonemeRules: [['tafkheem'], ['izhar']],
        });
        expect(cellWideRules(c)).toEqual([]);
    });

    it('a spelled-out letter keeps only what all its sounds name (كٓهيعٓصٓ)', () => {
        const c = cell({
            chars: 'ع', phonemeIndices: [7, 8, 9, 10],
            rules: ['madd_lazim', 'ikhfaa', 'tafkheem'],
            phonemeRules: [[], [], ['madd_lazim'], ['ikhfaa', 'tafkheem']],
        });
        expect(cellWideRules(c)).toEqual([]);
    });

    it('keeps a rule every phone names', () => {
        const c = cell({
            chars: 'م', phonemeIndices: [0, 1],
            rules: ['ghunnah', 'idgham_shafawi'],
            phonemeRules: [['ghunnah', 'idgham_shafawi'], ['ghunnah']],
        });
        expect(cellWideRules(c)).toEqual(['ghunnah']);
    });

    it('an ordinary cell is unchanged', () => {
        const c = cell({ chars: 'ق', phonemeIndices: [3], rules: ['tafkheem'] });
        expect(cellWideRules(c)).toEqual(['tafkheem']);
    });
});
