/**
 * Derive an analogous 3-color triad from a single accent hex.
 *
 * The Timestamps analysis display has three layers (word / letter / phoneme)
 * that must stay visually distinct yet harmonize with the user-chosen
 * highlight accent (the footer droplet). We rotate the accent hue by ±40° for
 * the letter / phoneme layers and clamp their lightness into a legible band on
 * the dark background, so changing the accent live-recolors all three layers
 * (plus the animation + waveform overlay) as one family.
 */

const LETTER_HUE_SHIFT = 40; // degrees
const PHONEME_HUE_SHIFT = -40; // degrees
// Legibility band for derived (non-word) layers on the dark panel bg.
const MIN_L = 0.5;
const MAX_L = 0.68;

export interface ColorTriad {
    word: string;
    letter: string;
    phoneme: string;
}

interface HSL {
    h: number; // 0..360
    s: number; // 0..1
    l: number; // 0..1
}

function clamp(v: number, lo: number, hi: number): number {
    return Math.min(hi, Math.max(lo, v));
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

function rgbToHsl(r: number, g: number, b: number): HSL {
    const rn = r / 255;
    const gn = g / 255;
    const bn = b / 255;
    const max = Math.max(rn, gn, bn);
    const min = Math.min(rn, gn, bn);
    const l = (max + min) / 2;
    const d = max - min;
    let h = 0;
    let s = 0;
    if (d !== 0) {
        s = d / (1 - Math.abs(2 * l - 1));
        switch (max) {
            case rn:
                h = ((gn - bn) / d) % 6;
                break;
            case gn:
                h = (bn - rn) / d + 2;
                break;
            default:
                h = (rn - gn) / d + 4;
        }
        h *= 60;
        if (h < 0) h += 360;
    }
    return { h, s, l };
}

function hslToHex({ h, s, l }: HSL): string {
    const c = (1 - Math.abs(2 * l - 1)) * s;
    const hp = ((h % 360) + 360) % 360 / 60;
    const x = c * (1 - Math.abs((hp % 2) - 1));
    let r = 0;
    let g = 0;
    let b = 0;
    if (hp < 1) [r, g, b] = [c, x, 0];
    else if (hp < 2) [r, g, b] = [x, c, 0];
    else if (hp < 3) [r, g, b] = [0, c, x];
    else if (hp < 4) [r, g, b] = [0, x, c];
    else if (hp < 5) [r, g, b] = [x, 0, c];
    else [r, g, b] = [c, 0, x];
    const m = l - c / 2;
    const toHex = (v: number): string =>
        clamp(Math.round((v + m) * 255), 0, 255).toString(16).padStart(2, '0');
    return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

function rotate(base: HSL, deg: number): string {
    return hslToHex({
        h: base.h + deg,
        // Keep at least some saturation so a near-grey accent still yields
        // distinguishable layers.
        s: clamp(base.s, 0.45, 1),
        l: clamp(base.l, MIN_L, MAX_L),
    });
}

/**
 * Build the analogous triad. The word layer is the accent verbatim; letter and
 * phoneme rotate ±40° and clamp lightness. Falls back to the historical
 * teal / blue if the accent can't be parsed.
 */
export function analogousTriad(accentHex: string): ColorTriad {
    const rgb = parseHex(accentHex);
    if (!rgb) {
        return { word: accentHex || '#4abad9', letter: '#2ec4b6', phoneme: '#4361ee' };
    }
    const base = rgbToHsl(rgb.r, rgb.g, rgb.b);
    return {
        word: accentHex,
        letter: rotate(base, LETTER_HUE_SHIFT),
        phoneme: rotate(base, PHONEME_HUE_SHIFT),
    };
}
