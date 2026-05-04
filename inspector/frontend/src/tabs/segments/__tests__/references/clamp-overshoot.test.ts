/**
 * _clampRefWordOvershoot — recoverable typo-fix path for refs whose word
 * exceeds the verse's word count.
 */

import { describe, it, expect } from 'vitest';
import { _clampRefWordOvershoot, parseSegRef } from '../../utils/data/references';

const vwc = { '1:1': 4, '1:2': 5 };

describe('_clampRefWordOvershoot', () => {
    it('end-word overshoot: clamps to verse word count', () => {
        const p = parseSegRef('1:1:1-1:1:9')!;
        const r = _clampRefWordOvershoot(p, vwc);
        expect(r).toEqual({ clampedRef: '1:1:1-1:1:4', clamped: true });
    });

    it('start-word overshoot: clamps to verse word count', () => {
        const p = parseSegRef('1:1:9-1:2:5')!;
        const r = _clampRefWordOvershoot(p, vwc);
        expect(r).toEqual({ clampedRef: '1:1:4-1:2:5', clamped: true });
    });

    it('both endpoints overshoot: clamps both', () => {
        const p = parseSegRef('1:1:9-1:2:99')!;
        const r = _clampRefWordOvershoot(p, vwc);
        expect(r).toEqual({ clampedRef: '1:1:4-1:2:5', clamped: true });
    });

    it('within bounds: passthrough with clamped=false', () => {
        const p = parseSegRef('1:1:2-1:2:3')!;
        const r = _clampRefWordOvershoot(p, vwc);
        expect(r).toEqual({ clampedRef: '1:1:2-1:2:3', clamped: false });
    });

    it('verse not in vwc: returns null (caller treats as unknown_verse)', () => {
        const p = parseSegRef('1:1:1-1:99:1')!;
        expect(_clampRefWordOvershoot(p, vwc)).toBeNull();
    });

    it('vwc unavailable: returns null', () => {
        const p = parseSegRef('1:1:1-1:1:2')!;
        expect(_clampRefWordOvershoot(p, undefined)).toBeNull();
    });
});
