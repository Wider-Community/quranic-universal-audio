import { describe, expect, it } from 'vitest';

import { waqfRenderFor, waqfRenderStyle } from '../waqf-render';

describe('waqfRenderFor', () => {
    it('returns the tuned calibration for a known mark (ۖ sala)', () => {
        expect(waqfRenderFor('ۖ')).toEqual({ scale: 1.02, shiftEm: -0.22, raiseEm: -0.24 });
    });

    it('returns the tuned calibration for the three-dot mark (ۛ)', () => {
        expect(waqfRenderFor('ۛ').scale).toBe(1.19);
    });

    it('falls back to the default for an unlisted mark', () => {
        expect(waqfRenderFor('م')).toEqual({ scale: 1, shiftEm: -0.16, raiseEm: -0.22 });
    });
});

describe('waqfRenderStyle', () => {
    it('projects the calibration onto the --waqf-* custom properties', () => {
        expect(waqfRenderStyle('ۖ')).toBe('--waqf-scale:1.02;--waqf-shift:-0.22em;--waqf-raise:-0.24em');
    });
});
