import { describe, expect, it } from 'vitest';

import type { TsValidationDoc } from '../../../../lib/types/generated/schemas';
import { groupTsValidationVerses } from '../validation-groups';

describe('groupTsValidationVerses', () => {
    it('places each verse in its highest failed beam only', () => {
        const doc: TsValidationDoc = {
            _meta: { beams: [50, 35, 20] },
            verses: {
                '1:3': { failed_beams: [35, 20], min_passing_beam: 50 },
                '1:2': { failed_beams: [20], min_passing_beam: 35 },
            },
        };

        expect(groupTsValidationVerses(doc)).toEqual([
            { beam: 35, refs: ['1:3'] },
            { beam: 20, refs: ['1:2'] },
        ]);
    });

    it('derives descending beam rows when meta beams are missing', () => {
        const doc: TsValidationDoc = {
            verses: {
                '2:10': { failed_beams: [20], min_passing_beam: 35 },
                '2:7': { failed_beams: [50], min_passing_beam: null },
            },
        };

        expect(groupTsValidationVerses(doc)).toEqual([
            { beam: 50, refs: ['2:7'] },
            { beam: 20, refs: ['2:10'] },
        ]);
    });

    it('sorts verse chips by numeric reference within a row', () => {
        const doc: TsValidationDoc = {
            _meta: { beams: [50, 20] },
            verses: {
                '2:10': { failed_beams: [20], min_passing_beam: 50 },
                '2:7': { failed_beams: [20], min_passing_beam: 50 },
            },
        };

        expect(groupTsValidationVerses(doc)).toEqual([
            { beam: 20, refs: ['2:7', '2:10'] },
        ]);
    });
});
