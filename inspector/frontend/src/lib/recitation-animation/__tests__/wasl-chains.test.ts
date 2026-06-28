import { describe, expect, it } from 'vitest';

import type { AnimUnit } from '../types';
import { buildWaslChains } from '../wasl-chains';

/** One unit per spec, in reading order; the unit's interval carries `waslTo`
 *  when the verse bridges (so it rides the verse's last word). */
function chain(specs: Array<[string, string?]>): AnimUnit[] {
    return specs.map(([location, waslTo], i) => {
        const [s, a, w] = location.split(':');
        const span = waslTo ? { start: i, end: i + 1, waslTo } : { start: i, end: i + 1 };
        return {
            location, ayahKey: `${s}:${a}`, surah: Number(s), ayah: Number(a), word: Number(w),
            text: location, start: i, end: i + 1, intervals: [span], letters: [],
        };
    });
}

describe('buildWaslChains', () => {
    it('links a single waṣl boundary into one chain', () => {
        const units = chain([['1:1:1'], ['1:1:2', '1:2'], ['1:2:1'], ['1:2:2']]);
        const c = buildWaslChains(units);
        expect(c.bridgesNext.has('1:1')).toBe(true);
        expect(c.chainStartOf.get('1:1')).toBe('1:1');
        expect(c.chainStartOf.get('1:2')).toBe('1:1');
        expect(c.chainEndIdxOf.get('1:1')).toBe(4); // end of verse 2's units
    });

    it('extends a 3-verse chain to its last verse end', () => {
        const units = chain([['1:1:1', '1:2'], ['1:2:1', '1:3'], ['1:3:1']]);
        const c = buildWaslChains(units);
        expect([...c.bridgesNext]).toEqual(['1:1', '1:2']);
        expect(c.chainStartOf.get('1:3')).toBe('1:1');
        expect(c.chainEndIdxOf.get('1:1')).toBe(3);
    });

    it('keeps each verse its own chain without waslTo (v9 no-op)', () => {
        const units = chain([['1:1:1'], ['1:2:1']]);
        const c = buildWaslChains(units);
        expect(c.bridgesNext.size).toBe(0);
        expect(c.chainStartOf.get('1:1')).toBe('1:1');
        expect(c.chainStartOf.get('1:2')).toBe('1:2');
        expect(c.chainEndIdxOf.get('1:2')).toBe(2);
    });

    it('ignores a waslTo that does not target the next reading-order verse', () => {
        const units = chain([['1:1:1', '1:9'], ['1:2:1']]);
        const c = buildWaslChains(units);
        expect(c.bridgesNext.has('1:1')).toBe(false);
        expect(c.chainStartOf.get('1:1')).toBe('1:1');
    });
});
