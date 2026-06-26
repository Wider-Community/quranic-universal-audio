/**
 * Derive an analogous 3-colour triad — and the legible ink for each — from a
 * single accent hex.
 *
 * The Timestamps analysis display has three layers (word / letter / phoneme)
 * that must stay visually distinct yet harmonise with the user-chosen highlight
 * accent (the footer droplet). Two things have to hold for any picked colour:
 *
 *  1. Perceptual consistency. The siblings are derived by ROTATING HUE around
 *     the accent. Done in HSL this drifts badly — equal HSL "lightness" reads as
 *     wildly different perceived brightness across hues (a yellow and a blue at
 *     HSL L=0.5 differ ~2× to the eye), so a light-friendly accent yields dark
 *     siblings and vice-versa. We work in OKLCh instead (the space the CSS
 *     tokens already use): both siblings inherit the accent's perceptual
 *     lightness and a chroma floor, so all three read as one equally-legible
 *     family. Lightness is clamped into a legible band on the dark panel, so an
 *     extreme pick (near-black / glaring) is lifted/lowered — all three together.
 *
 *  2. Readable ink. When a colour is used as a FILL behind text (the active
 *     word / letter / phoneme cells), the glyph must auto-switch black-or-white
 *     for contrast. `inkFor()` is the universal WCAG-2 relative-luminance pick
 *     (crossover at L≈0.179, the contrast-optimal point), so the ink stays
 *     readable whatever hue/lightness the fill lands on. It also drives the
 *     teleprompter's active-word outline (a light halo lifts a dark accent off
 *     the dark page; a dark halo crisps a light one).
 *
 * Changing the accent live-recolours all three layers, their inks, the waveform
 * overlay and the teleprompter as one reactive family.
 */

const LETTER_HUE_SHIFT = 40; // OKLCh degrees
const PHONEME_HUE_SHIFT = -40; // OKLCh degrees
// Legibility band for OKLCh lightness on the dark panel bg. The accent's own
// lightness is honoured verbatim when it already sits in-band (common case);
// only an out-of-band pick is pulled in — and the siblings always share the
// (clamped) accent lightness, so the family never diverges.
const MIN_L = 0.62;
const MAX_L = 0.84;
// Chroma floor for the derived siblings so a near-grey accent still yields
// distinguishable layers (the word keeps the accent's own chroma).
const MIN_C = 0.085;

// Ink endpoints. A near-black navy (matches the panel family) and pure white;
// `inkFor` picks whichever clears WCAG contrast on the given fill.
const DARK_INK = '#1a1a2e';
const LIGHT_INK = '#ffffff';
// Black-vs-white luminance crossover: solving (L+0.05)/0.05 = 1.05/(L+0.05)
// gives L = √0.0525 − 0.05 ≈ 0.17913 — the contrast-optimal switch point (not
// the naive 0.5, which skips linearisation and over-picks white on mid-tones).
const INK_CROSSOVER = Math.sqrt(0.0525) - 0.05;

export interface ColorTriad {
    word: string;
    letter: string;
    phoneme: string;
}

interface Oklch {
    L: number; // 0..1 perceptual lightness
    C: number; // ≥0 chroma
    h: number; // hue degrees
}

function clamp(v: number, lo: number, hi: number): number {
    return Math.min(hi, Math.max(lo, v));
}

/** sRGB 8-bit channel → linear-light (WCAG / sRGB transfer fn). */
function srgbToLinear(c8: number): number {
    const c = c8 / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

/** Linear-light → sRGB 0..255 (inverse transfer fn); input clamped to [0,1]. */
function linearToSrgb(x: number): number {
    const c = clamp(x, 0, 1);
    const v = c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055;
    return clamp(Math.round(v * 255), 0, 255);
}

/** Parse #rgb / #rrggbb (with or without leading #) → {r,g,b} 0..255, or null. */
function parseHex(hex: string): { r: number; g: number; b: number } | null {
    let h = hex.trim().replace(/^#/, '');
    if (h.length === 3) {
        h = h.split('').map((c) => c + c).join('');
    }
    if (h.length !== 6 || /[^0-9a-fA-F]/.test(h)) return null;
    return {
        r: parseInt(h.slice(0, 2), 16),
        g: parseInt(h.slice(2, 4), 16),
        b: parseInt(h.slice(4, 6), 16),
    };
}

function toHex(r: number, g: number, b: number): string {
    const h = (v: number): string => v.toString(16).padStart(2, '0');
    return `#${h(r)}${h(g)}${h(b)}`;
}

/** WCAG-2 relative luminance (0 black .. 1 white) of an sRGB colour. */
function relLuminance(r: number, g: number, b: number): number {
    return 0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b);
}

// ---- OKLab/OKLCh (Ottosson 2020) — reference matrices ----

function hexToOklch(rgb: { r: number; g: number; b: number }): Oklch {
    const r = srgbToLinear(rgb.r);
    const g = srgbToLinear(rgb.g);
    const b = srgbToLinear(rgb.b);
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
    const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
    const B = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
    return { L, C: Math.hypot(A, B), h: (Math.atan2(B, A) * 180) / Math.PI };
}

/** OKLCh → linear-light RGB (may be out of [0,1] gamut). */
function oklchToLinearRgb({ L, C, h }: Oklch): [number, number, number] {
    const A = C * Math.cos((h * Math.PI) / 180);
    const B = C * Math.sin((h * Math.PI) / 180);
    const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3;
    const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3;
    const s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3;
    return [
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
    ];
}

function inGamut(c: Oklch): boolean {
    const e = 1e-4;
    return oklchToLinearRgb(c).every((v) => v >= -e && v <= 1 + e);
}

/**
 * OKLCh → sRGB hex, gamut-mapped by L-preserving chroma reduction. Rotating hue
 * at fixed (L,C) routinely leaves the sRGB gamut (max chroma varies strongly by
 * hue); a naive per-channel clip would shift hue/lightness and defeat the
 * perceptual-consistency goal. Instead we hold L and h and binary-search chroma
 * down until in-gamut — the eye tolerates a chroma dip far better than a
 * lightness jump (the CSS Color 4 baseline approach).
 */
function oklchToHex(c: Oklch): string {
    let mapped = c;
    if (!inGamut(c)) {
        let lo = 0;
        let hi = c.C;
        for (let i = 0; i < 12; i++) {
            const mid = (lo + hi) / 2;
            if (inGamut({ L: c.L, C: mid, h: c.h })) lo = mid;
            else hi = mid;
        }
        mapped = { L: c.L, C: lo, h: c.h };
    }
    const [r, g, b] = oklchToLinearRgb(mapped);
    return toHex(linearToSrgb(r), linearToSrgb(g), linearToSrgb(b));
}

/**
 * Pick a legible ink (near-black or white) for text/glyphs sitting ON a fill of
 * the given colour — the universal WCAG-2 relative-luminance method. Reactive:
 * recompute whenever the fill (accent / triad colour) changes. Falls back to
 * dark ink for an unparseable colour.
 */
export function inkFor(fillHex: string): string {
    const rgb = parseHex(fillHex);
    if (!rgb) return DARK_INK;
    return relLuminance(rgb.r, rgb.g, rgb.b) > INK_CROSSOVER ? DARK_INK : LIGHT_INK;
}

/**
 * Build the analogous triad in OKLCh. The word layer is the accent at its own
 * chroma (verbatim when already in the legible lightness band); letter and
 * phoneme rotate hue ±40° and share the accent's clamped lightness with a chroma
 * floor, gamut-mapped so every result is a real sRGB colour. Falls back to the
 * historical teal / blue if the accent can't be parsed.
 */
export function analogousTriad(accentHex: string): ColorTriad {
    const rgb = parseHex(accentHex);
    if (!rgb) {
        return { word: accentHex || '#4abad9', letter: '#2ec4b6', phoneme: '#4361ee' };
    }
    const base = hexToOklch(rgb);
    const L = clamp(base.L, MIN_L, MAX_L);
    const sibC = Math.max(base.C, MIN_C);
    const word = L === base.L
        ? toHex(rgb.r, rgb.g, rgb.b)
        : oklchToHex({ L, C: base.C, h: base.h });
    return {
        word,
        letter: oklchToHex({ L, C: sibC, h: base.h + LETTER_HUE_SHIFT }),
        phoneme: oklchToHex({ L, C: sibC, h: base.h + PHONEME_HUE_SHIFT }),
    };
}
