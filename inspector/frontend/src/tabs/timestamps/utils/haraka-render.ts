/**
 * Per-glyph render calibration for a bare combining diacritic mark (haraka /
 * tanwīn / dagger-alef / mini-meem) rendered standalone inside a small
 * diacritic cell of the analysis letter row.
 *
 * A lone haraka is a zero-width combining glyph whose ink sits at a different
 * size/offset in the em per mark, so the glyph size and centring offset cannot
 * be shared across marks. These values were tuned against the DigitalKhatt face
 * in the diacritic-cell sizing playground (`design/prototypes/haraka-cells/`),
 * keyed by the mark's codepoint (lowercase hex). They are the data the CSS reads
 * — `UnifiedDisplay` projects them onto the `--haraka-*` custom properties via
 * `harakaRenderStyle`, and the generic `.haraka-cell .g` rule consumes them
 * (`font-size: …*var(--haraka-scale)`, `transform: translate(var(--haraka-shift), var(--haraka-raise))`).
 *
 * Mirrors `utils/waqf-render.ts` exactly (same shape, same projection contract).
 */

export interface HarakaRender {
    /** Glyph font-size as a multiple of the analysis letter font. */
    scale: number;
    /** Horizontal nudge to centre the ink (em of the glyph; − = left). */
    shiftEm: number;
    /** Vertical nudge to centre/raise the ink (em of the glyph; − = up). */
    raiseEm: number;
}

/** Fallback for any surfaced mark without an explicit entry. */
const DEFAULT_RENDER: HarakaRender = { scale: 1.4, shiftEm: 0, raiseEm: 0 };

/** Codepoint-hex → calibration for single small-cell marks (short vowels +
 *  tanwins, incl. the open DK tanwin forms 8f0-8f2). Tuned against DigitalKhatt.
 *  The dagger-alef renders as a FULL madd cell (no entry). An iqlab tanwīn is
 *  TWO cells (haraka + a standalone mini-meem); the mini-meem glyphs (6e2 above,
 *  6ed below) carry their OWN calibration since the meem ink sits differently
 *  from a haraka. */
const BY_CODEPOINT: Record<string, HarakaRender> = {
    '64e': { scale: 1.01, shiftEm: -0.11, raiseEm: -0.335 }, // fatha
    '64f': { scale: 0.9, shiftEm: -0.11, raiseEm: -0.215 }, // damma
    '650': { scale: 0.99, shiftEm: -0.125, raiseEm: -0.24 }, // kasra
    '64b': { scale: 0.62, shiftEm: -0.115, raiseEm: -0.23 }, // fathatan (stacked)
    '64c': { scale: 0.9, shiftEm: -0.13, raiseEm: -0.17 }, // dammatan (stacked)
    '64d': { scale: 1.09, shiftEm: -0.125, raiseEm: -0.23 }, // kasratan (stacked)
    '8f0': { scale: 1.15, shiftEm: -0.145, raiseEm: -0.345 }, // fathatan open (DK U+08F0)
    '8f1': { scale: 0.79, shiftEm: -0.205, raiseEm: -0.24 }, // dammatan open (U+08F1)
    '8f2': { scale: 1.13, shiftEm: -0.11, raiseEm: -0.355 }, // kasratan open (U+08F2)
    '6e2': { scale: 0.8, shiftEm: -0.035, raiseEm: -0.325 }, // mini-meem above (iqlab, U+06E2)
    '6ed': { scale: 0.81, shiftEm: -0.09, raiseEm: -0.445 }, // mini-meem below (iqlab, U+06ED)
};

/** Calibration for a glyph keyed by its leading codepoint. */
export function harakaRenderFor(glyph: string): HarakaRender {
    const cp = glyph.codePointAt(0)?.toString(16);
    return (cp && BY_CODEPOINT[cp]) || DEFAULT_RENDER;
}

/** Inline `style` string projecting a glyph's calibration to the `--haraka-*`
 *  vars the `.haraka-cell .g` CSS rule reads. `extraShiftEm` nudges horizontally
 *  on top of the calibrated shift. */
export function harakaRenderStyle(glyph: string, extraShiftEm = 0): string {
    const r = harakaRenderFor(glyph);
    return `--haraka-scale:${r.scale};--haraka-shift:${(r.shiftEm + extraShiftEm).toFixed(3)}em;--haraka-raise:${r.raiseEm}em`;
}
