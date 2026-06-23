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

/** Codepoint (hex) → calibration. Tuned against DigitalKhatt in the diacritic-
 *  cell playground. Only the SMALL-cell short-vowel + tanwīn marks are listed:
 *  the dagger-alef (ٰ) renders as a FULL madd cell (its own grapheme, no centring
 *  override), and the iqlab mini-meem rides WITH its haraka (it composes onto the
 *  haraka glyph and inherits the haraka's calibration — no separate entry). */
const BY_CODEPOINT: Record<string, HarakaRender> = {
    '64e': { scale: 1.5, shiftEm: -0.115, raiseEm: -0.35 }, // َ fatḥa
    '64f': { scale: 1.24, shiftEm: -0.155, raiseEm: -0.2 }, // ُ ḍamma
    '650': { scale: 1.49, shiftEm: -0.105, raiseEm: -0.3 }, //  ِ kasra
    '64b': { scale: 1.54, shiftEm: -0.1, raiseEm: -0.305 }, //  ً fatḥatan
    '64c': { scale: 1.1, shiftEm: -0.145, raiseEm: -0.14 }, //  ٌ ḍammatan
    '64d': { scale: 1.5, shiftEm: -0.12, raiseEm: -0.26 }, //   ٍ kasratan
};

/** Calibration for a single diacritic glyph (defaults if the mark is unlisted). */
export function harakaRenderFor(glyph: string): HarakaRender {
    const cp = glyph.codePointAt(0)?.toString(16);
    return (cp && BY_CODEPOINT[cp]) || DEFAULT_RENDER;
}

/** Inline `style` string projecting a glyph's calibration to the `--haraka-*`
 *  vars the `.haraka-cell .g` CSS rule reads. `extraShiftEm` nudges the glyph
 *  horizontally on top of its calibrated shift (used to slide the fused iqlab
 *  haraka+mini-meem slightly right). */
export function harakaRenderStyle(glyph: string, extraShiftEm = 0): string {
    const r = harakaRenderFor(glyph);
    return `--haraka-scale:${r.scale};--haraka-shift:${(r.shiftEm + extraShiftEm).toFixed(3)}em;--haraka-raise:${r.raiseEm}em`;
}
