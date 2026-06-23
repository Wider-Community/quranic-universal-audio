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
 *  The dagger-alef renders as a FULL madd cell (no entry). The iqlab composites
 *  (haraka + mini-meem) carry their OWN calibration under a named key
 *  (iqlab_fatha/damma/kasra) since the mini-meem shifts the ink. */
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
    'iqlab_fatha': { scale: 0.79, shiftEm: -0.015, raiseEm: -0.365 }, // fatha + mini-meem
    'iqlab_damma': { scale: 0.8, shiftEm: -0.055, raiseEm: -0.285 }, // damma + mini-meem
    'iqlab_kasra': { scale: 0.81, shiftEm: -0.09, raiseEm: -0.485 }, // kasra + mini-meem
};

/** Calibration for a glyph OR an explicit named key. Named keys (iqlab composites)
 *  resolve first; otherwise the glyph's leading codepoint. */
export function harakaRenderFor(keyOrGlyph: string): HarakaRender {
    if (BY_CODEPOINT[keyOrGlyph]) return BY_CODEPOINT[keyOrGlyph];
    const cp = keyOrGlyph.codePointAt(0)?.toString(16);
    return (cp && BY_CODEPOINT[cp]) || DEFAULT_RENDER;
}

/** Inline `style` string projecting a glyph's calibration to the `--haraka-*`
 *  vars the `.haraka-cell .g` CSS rule reads. `extraShiftEm` nudges horizontally on
 *  top of the calibrated shift; `calibKey` selects an explicit calibration (e.g. an
 *  iqlab composite) instead of the glyph's codepoint. */
export function harakaRenderStyle(glyph: string, extraShiftEm = 0, calibKey?: string): string {
    const r = harakaRenderFor(calibKey ?? glyph);
    return `--haraka-scale:${r.scale};--haraka-shift:${(r.shiftEm + extraShiftEm).toFixed(3)}em;--haraka-raise:${r.raiseEm}em`;
}
