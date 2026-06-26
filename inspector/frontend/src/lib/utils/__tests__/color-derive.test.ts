import { describe, expect, it } from 'vitest';

import { analogousTriad, inkFor, mutedFor } from '../color-derive';

const HEX6 = /^#[0-9a-f]{6}$/;
const DARK_INK = '#1a1a2e';
const LIGHT_INK = '#ffffff';

describe('inkFor', () => {
    it('picks dark ink on a white fill and light ink on a black fill', () => {
        expect(inkFor('#ffffff')).toBe(DARK_INK);
        expect(inkFor('#000000')).toBe(LIGHT_INK);
    });

    it('uses the WCAG 0.179 crossover, not a naive 0.5 luminance threshold', () => {
        // Mid grey #808080 has relative luminance ≈ 0.216 — above the 0.179
        // black/white crossover, so dark ink wins. A 0.5-threshold impl would
        // wrongly pick white here.
        expect(inkFor('#808080')).toBe(DARK_INK);
    });

    it('returns dark ink for an unparseable colour', () => {
        expect(inkFor('not-a-color')).toBe(DARK_INK);
    });
});

describe('analogousTriad', () => {
    it('emits three valid sRGB hex colours', () => {
        const t = analogousTriad('#4abad9');
        expect(t.word).toMatch(HEX6);
        expect(t.letter).toMatch(HEX6);
        expect(t.phoneme).toMatch(HEX6);
    });

    it('keeps an in-band accent verbatim as the word layer', () => {
        expect(analogousTriad('#4abad9').word).toBe('#4abad9');
    });

    it('makes the three layers visually distinct', () => {
        const t = analogousTriad('#4abad9');
        expect(t.letter).not.toBe(t.word);
        expect(t.phoneme).not.toBe(t.word);
        expect(t.letter).not.toBe(t.phoneme);
    });

    it('lifts an out-of-band dark accent into the legible band', () => {
        const t = analogousTriad('#000000');
        expect(t.word).not.toBe('#000000');
        // Lifted into the light band → dark ink reads on every layer.
        expect(inkFor(t.word)).toBe(DARK_INK);
    });

    it('lowers a glaring accent into the legible band', () => {
        expect(analogousTriad('#ffff00').word).not.toBe('#ffff00');
    });

    it('keeps the three layers at one legibility level (consistent ink)', () => {
        // The reported HSL bug: a light accent yielded dark siblings. The OKLCh
        // derivation locks all three to one perceptual lightness, so they always
        // land on the same side of the ink crossover.
        for (const accent of ['#4abad9', '#f0a500', '#222266', '#e0457b', '#33dd55']) {
            const t = analogousTriad(accent);
            const ink = inkFor(t.word);
            expect(inkFor(t.letter)).toBe(ink);
            expect(inkFor(t.phoneme)).toBe(ink);
        }
    });

    it('falls back to the historical triad for an empty accent', () => {
        const t = analogousTriad('');
        expect(t.word).toBe('#4abad9');
        expect(t.letter).toBe('#2ec4b6');
        expect(t.phoneme).toBe('#4361ee');
    });
});

describe('mutedFor', () => {
    it('emits a valid sRGB hex', () => {
        expect(mutedFor('#2ec4b6')).toMatch(HEX6);
    });

    it('returns the input verbatim for an unparseable colour', () => {
        expect(mutedFor('not-a-color')).toBe('not-a-color');
    });

    it('keeps the fill ink readable on its own ghost track (the wipe invariant)', () => {
        // The single auto-contrast ink chosen for the FULL fill must also read on
        // the unfilled ghost, so the karaoke glyph stays legible across the sweep.
        for (const fill of ['#4abad9', '#f0a500', '#2ec4b6', '#4361ee', '#e0457b', '#33dd55', '#222266']) {
            expect(inkFor(mutedFor(fill))).toBe(inkFor(fill));
        }
    });

    it('desaturates the fill (ghost reads as fainter, not a second hue)', () => {
        // Pure-ish saturated fills must come back lower-chroma — a near-grey track,
        // not a rival colour competing with the full fill blooming over it.
        const ghost = mutedFor('#2ec4b6');
        expect(ghost).not.toBe('#2ec4b6');
    });
});
