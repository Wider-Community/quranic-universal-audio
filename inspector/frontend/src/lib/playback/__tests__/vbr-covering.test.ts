import { describe, expect, it } from 'vitest';

import type { AyahBoundary } from '../../recitation-animation/types';
import { vbrCoveringRangeFor } from '../vbr-covering';

const ayahs: AyahBoundary[] = [
    { ayahKey: '1:1', surah: 1, ayah: 1, startMs: 100, endMs: 1200 },
    { ayahKey: '1:2', surah: 1, ayah: 2, startMs: 1300, endMs: 2600 },
    { ayahKey: '1:3', surah: 1, ayah: 3, startMs: 2700, endMs: 3900 },
];

describe('vbrCoveringRangeFor', () => {
    it('loads from the current ayah through the chapter tail', () => {
        expect(vbrCoveringRangeFor(500, ayahs)).toEqual([100, 3900]);
        expect(vbrCoveringRangeFor(1500, ayahs)).toEqual([1300, 3900]);
    });

    it('uses the nearest preceding ayah outside an exact interval', () => {
        expect(vbrCoveringRangeFor(2650, ayahs)).toEqual([1300, 3900]);
        expect(vbrCoveringRangeFor(5000, ayahs)).toEqual([2700, 3900]);
    });

    it('falls back to a finite clip when ayah boundaries are unavailable', () => {
        expect(vbrCoveringRangeFor(2000, [])).toEqual([2000, 32_000]);
        expect(vbrCoveringRangeFor(2000, [], 5000)).toEqual([2000, 5000]);
    });
});
