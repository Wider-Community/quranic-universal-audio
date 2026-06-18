/**
 * Per-mark render calibration for a STANDALONE waqf (stop) mark in the analysis
 * pause-bridge cell.
 *
 * A lone waqf mark is a zero-width combining glyph, and each mark's ink sits at a
 * different size/offset in the em, so the glyph size and centring offset cannot be
 * shared across marks. These values were tuned against the DigitalKhatt face in the
 * waqf sizing playground, keyed by the mark's codepoint (lowercase hex). They are
 * the data the CSS reads — `UnifiedDisplay` projects them onto the `--waqf-*` custom
 * properties via `waqfRenderStyle`, and the generic `.pause-waqf` rule consumes them
 * (`font-size: …*var(--waqf-scale)`, `transform: translate(var(--waqf-shift), var(--waqf-raise))`).
 */

export interface WaqfRender {
    /** Glyph font-size as a multiple of the analysis word font. */
    scale: number;
    /** Horizontal nudge to centre the ink (em of the glyph; − = left). */
    shiftEm: number;
    /** Vertical nudge to centre/raise the ink (em of the glyph; − = up). */
    raiseEm: number;
}

/** Fallback for any surfaced mark without an explicit entry. */
const DEFAULT_RENDER: WaqfRender = { scale: 1, shiftEm: -0.16, raiseEm: -0.22 };

/** Codepoint (hex) → calibration. Tuned in the waqf sizing playground. */
const BY_CODEPOINT: Record<string, WaqfRender> = {
    '6d6': { scale: 1.02, shiftEm: -0.22, raiseEm: -0.24 }, // ۖ sala
    '6d7': { scale: 1.0, shiftEm: -0.16, raiseEm: -0.22 }, //  ۗ qila
    '6d8': { scale: 0.99, shiftEm: -0.24, raiseEm: -0.2 }, //  ۘ meem (lazim)
    '6da': { scale: 1.01, shiftEm: -0.12, raiseEm: -0.23 }, // ۚ jeem (jaiz)
    '6db': { scale: 1.19, shiftEm: -0.12, raiseEm: -0.3 }, //  ۛ muanaqah (three dots)
};

/** Calibration for a single waqf mark (defaults if the mark is unlisted). */
export function waqfRenderFor(mark: string): WaqfRender {
    const cp = mark.codePointAt(0)?.toString(16);
    return (cp && BY_CODEPOINT[cp]) || DEFAULT_RENDER;
}

/** Inline `style` string projecting a mark's calibration to the `--waqf-*` vars
 *  the `.pause-waqf` CSS rule reads. */
export function waqfRenderStyle(mark: string): string {
    const r = waqfRenderFor(mark);
    return `--waqf-scale:${r.scale};--waqf-shift:${r.shiftEm}em;--waqf-raise:${r.raiseEm}em`;
}
