/**
 * The single source of truth for the Timestamps highlight colours.
 *
 * One function — `resolveHighlightVars` — turns the user's accent (the footer
 * droplet) plus a `HighlightModel` into the full set of CSS custom properties
 * the analysis cells read. Every surface (idle cells, active cells, the karaoke
 * wipe, both highlight modes, light/dark) is driven from this one resolve, so
 * there is no per-surface drift: change the model in one place and the whole
 * display follows.
 *
 * The model splits the active/idle treatment into two independent tiers — a
 * `word` tier and a `letterPhoneme` tier — each a self-contained `TierStyle`
 * (fill + ink + idle, with that tier's own tints/opacity/customs). Global
 * fields (theme, the accent→triad mapping) and the karaoke track are shared.
 *
 * The shipped defaults (`DEFAULT_HIGHLIGHT_MODEL`) are the tuned treatment: an
 * accent-tint fill per tier (dark ink on the bold word, white on the smaller
 * letter/phoneme cells), with lightness held in the legible band. The lab
 * (`tabs/timestamps/stores/highlight-lab`) feeds overrides to explore
 * alternatives (deep/bright fills, auto/accent inks, the karaoke track colour,
 * the band + hue mapping, a light theme) live.
 */
import {
    analogousTriadCfg,
    deepForCfg,
    inkFor,
    legibleAccentCfg,
    type ColorTriad,
    type TriadCfg,
} from './color-derive';

/** How the active cell's FILL derives from its tier colour. */
export type FillModel = 'bright' | 'deep' | 'tint';
/** How a glyph's INK is chosen on a fill. */
export type InkModel = 'auto' | 'white' | 'black' | 'accent' | 'custom';
/** How an idle (resting) cell's glyph is coloured. */
export type IdleModel = 'accent' | 'grey' | 'dim-accent' | 'custom';
/** The karaoke wipe's not-yet-reached (track) base colour. */
export type TrackModel = 'fill' | 'bright' | 'rest' | 'custom';
export type Theme = 'dark' | 'light';

/** A complete, independent styling for one tier (word, or letter/phoneme):
 *  its active fill + the glyph ink on that fill + its idle glyph, each with the
 *  tier's own tuning. The two tiers never share a custom value. */
export interface TierStyle {
    fill: FillModel;
    tintPct: number; // 'tint' only — % of tier colour mixed onto the rest bg
    opacityPct: number; // % of the fill mixed onto the rest bg (100 = solid)
    deepMaxLum: number; // 'deep' only — luminance ceiling for the dark fill
    ink: InkModel;
    inkCustom: string;
    idle: IdleModel;
    idleCustom: string;
}

export interface HighlightModel {
    theme: Theme;
    // ---- mapping (accent → triad), shared by both tiers ----
    letterShift: number;
    phonemeShift: number;
    chromaFloor: number;
    bandMinL: number;
    bandMaxL: number;
    // ---- per-tier active/idle styling ----
    word: TierStyle;
    letterPhoneme: TierStyle;
    // ---- karaoke wipe (the not-yet-sung portion), shared by both tiers ----
    track: TrackModel;
    trackPct: number; // % of the track colour mixed onto the rest bg
    trackCustom: string;
}

export const DEFAULT_HIGHLIGHT_MODEL: HighlightModel = {
    theme: 'dark',
    letterShift: 40,
    phonemeShift: -40,
    chromaFloor: 0.085,
    bandMinL: 0.66,
    bandMaxL: 0.86,
    // Active word: a 70% accent tint with dark (bold, large) ink.
    word: {
        fill: 'tint', tintPct: 70, opacityPct: 100, deepMaxLum: 0.245,
        ink: 'black', inkCustom: '#ffffff', idle: 'grey', idleCustom: '#aaaaaa',
    },
    // Active letter/phoneme cells: a darker 50% tint with white ink.
    letterPhoneme: {
        fill: 'tint', tintPct: 50, opacityPct: 100, deepMaxLum: 0.275,
        ink: 'white', inkCustom: '#ffffff', idle: 'grey', idleCustom: '#aaaaaa',
    },
    track: 'fill',
    trackPct: 20,
    trackCustom: '#727288',
};

/** The light-theme treatment. Same tints and hue mapping, but a DARKER legible
 *  band (so the triad reads as ink on a near-white cell rather than as a pale
 *  light-on-dark wash) and AUTO ink on the smaller letter/phoneme cells — a pale
 *  tint wants a dark glyph, which `inkFor` derives from the resolved fill. The
 *  dark-theme deep-block fill (a near-black slab with white text) is deliberately
 *  NOT used on light; the soft tint + auto ink keeps the analysis frame calm. */
export const LIGHT_HIGHLIGHT_MODEL: HighlightModel = {
    ...DEFAULT_HIGHLIGHT_MODEL,
    theme: 'light',
    bandMinL: 0.46,
    bandMaxL: 0.70,
    word: { ...DEFAULT_HIGHLIGHT_MODEL.word, ink: 'black' },
    letterPhoneme: { ...DEFAULT_HIGHLIGHT_MODEL.letterPhoneme, ink: 'auto' },
    trackCustom: '#c9cfdd',
};

/** The shipped highlight model for a theme. */
export function modelForTheme(theme: Theme): HighlightModel {
    return theme === 'light' ? LIGHT_HIGHLIGHT_MODEL : DEFAULT_HIGHLIGHT_MODEL;
}

/** The accent → word/letter/phoneme triad in the theme's legible band (so the
 *  waveform's tier-coloured markers track the analysis cells and stay legible on
 *  the themed waveform background). */
export function triadForTheme(accentHex: string, theme: Theme): ColorTriad {
    return analogousTriadCfg(accentHex, tier(modelForTheme(theme)));
}

/** The shipping accent palette — the quick-pick swatches in the user's droplet
 *  picker (`HighlightColorPicker`). Each is a band-legible accent. Curate via the
 *  highlight lab's "Shipped presets" panel, then paste its exported array here. */
export const SHIPPED_HIGHLIGHT_PRESETS: string[] = [
    '#d09b6b', '#b7aa48', '#82b692', '#00c86f', '#60bba4', '#4abad9', '#8aa4f0', '#a8a8a8',
];

const GREY = '#aaa';
// The idle (non-active) glyph on the LIGHT theme: #aaa is legible-on-dark but
// washes out on the near-white cell, so light gets a darker cool grey that still
// reads as "secondary" against the near-black active ink.
const GREY_LIGHT = 'oklch(0.48 0.015 268)';
const DARK_INK = '#1a1a2e';
const REST = 'var(--hl-cell-rest)';

/** Light-theme surface overrides, scoped to the analysis frame. */
const LIGHT_SURFACE: Record<string, string> = {
    '--hl-cell-rest': '#eef0f5',
    '--hl-cell-wash': '#dfe3ec',
    '--hl-frame-bg': '#f5f6fa',
};

/** The concrete --hl-cell-rest per theme. A `tint` fill is `color-mix(in srgb,
 *  base X%, var(--hl-cell-rest))`; auto-ink must measure that fill's luminance,
 *  but a color-mix STRING can't be measured, so we resolve the mix numerically
 *  against this rest. Keeping these in lockstep with LIGHT_SURFACE / the dark
 *  --hl-cell-rest is what makes auto-ink land a readable glyph in both themes. */
const REST_HEX: Record<Theme, string> = { dark: '#0f0f23', light: '#eef0f5' };

function parseHexLocal(hex: string): [number, number, number] | null {
    let h = hex.trim().replace(/^#/, '');
    if (h.length === 3) h = h.split('').map((c) => c + c).join('');
    if (h.length !== 6 || /[^0-9a-fA-F]/.test(h)) return null;
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

/** Resolve `color-mix(in srgb, aHex aPct%, restHex)` to a concrete hex (naive
 *  per-channel gamma interpolation — matches srgb color-mix, exact enough for a
 *  black-vs-white ink decision). Returns aHex unchanged if either is unparseable. */
function mixSrgb(aHex: string, restHex: string, aPct: number): string {
    const a = parseHexLocal(aHex);
    const b = parseHexLocal(restHex);
    if (!a || !b) return aHex;
    const p = Math.max(0, Math.min(100, aPct)) / 100;
    const to2 = (v: number): string => Math.round(v).toString(16).padStart(2, '0');
    return `#${to2(a[0] * p + b[0] * (1 - p))}${to2(a[1] * p + b[1] * (1 - p))}${to2(a[2] * p + b[2] * (1 - p))}`;
}

function tier(m: HighlightModel): TriadCfg {
    return {
        letterShift: m.letterShift,
        phonemeShift: m.phonemeShift,
        chromaFloor: m.chromaFloor,
        minL: m.bandMinL,
        maxL: m.bandMaxL,
    };
}

/** The solid (pre-opacity) fill for a tier colour under its fill model — as a
 *  CSS string applied to the cell (tint stays a live color-mix so it tracks the
 *  themed --hl-cell-rest). */
function fillColor(base: string, s: TierStyle): string {
    if (s.fill === 'deep') return deepForCfg(base, s.deepMaxLum);
    if (s.fill === 'tint') return `color-mix(in srgb, ${base} ${s.tintPct}%, ${REST})`;
    return base; // 'bright'
}

/** The same fill resolved to a CONCRETE hex (against the theme's rest), for the
 *  auto-ink luminance decision. */
function solidHexFor(base: string, s: TierStyle, theme: Theme): string {
    if (s.fill === 'deep') return deepForCfg(base, s.deepMaxLum);
    if (s.fill === 'tint') return mixSrgb(base, REST_HEX[theme], s.tintPct);
    return base; // 'bright'
}

/** Apply the fill opacity (mix onto the rest bg) — 100% leaves it solid. */
function withOpacity(fill: string, s: TierStyle): string {
    return s.opacityPct >= 100 ? fill : `color-mix(in srgb, ${fill} ${s.opacityPct}%, ${REST})`;
}

/** The glyph ink on an active fill. `auto` picks black-or-white by the WCAG
 *  luminance of the CONCRETE fill hex (so it lands a readable glyph on any tint
 *  in either theme — a pale light-theme tint gets a dark glyph, a deep dark-theme
 *  fill gets white). */
function inkColor(solidHex: string, base: string, s: TierStyle): string {
    switch (s.ink) {
        case 'white': return '#fff';
        case 'black': return DARK_INK;
        case 'accent': return base;
        case 'custom': return s.inkCustom;
        case 'auto': return inkFor(solidHex);
    }
}

function idleInk(base: string, s: TierStyle, theme: Theme): string {
    const grey = theme === 'light' ? GREY_LIGHT : GREY;
    switch (s.idle) {
        case 'accent': return base;
        case 'grey': return grey;
        case 'dim-accent': return `color-mix(in srgb, ${base} 55%, ${grey})`;
        case 'custom': return s.idleCustom;
    }
}

/** The karaoke not-yet-reached base for a tier (mixed onto the rest bg). */
function trackColor(base: string, solidFill: string, m: HighlightModel): string {
    if (m.track === 'rest') return REST;
    const src = m.track === 'bright' ? base
        : m.track === 'custom' ? m.trackCustom
        : solidFill; // 'fill'
    return `color-mix(in srgb, ${src} ${m.trackPct}%, ${REST})`;
}

/**
 * Resolve every highlight CSS var from the accent + model. Returns a flat
 * `{ '--var': value }` map ready to spread onto the `#timestamps-panel`
 * container; transform-dependent values are recomputed reactively upstream.
 */
export function resolveHighlightVars(accentHex: string, m: HighlightModel): Record<string, string> {
    const t: ColorTriad = analogousTriadCfg(accentHex, tier(m));
    const out: Record<string, string> = {};

    const tiers: Array<[keyof ColorTriad, string, TierStyle]> = [
        ['word', '--anim-highlight-color', m.word],
        ['letter', '--ts-letter-color', m.letterPhoneme],
        ['phoneme', '--ts-phoneme-color', m.letterPhoneme],
    ];

    for (const [key, colorVar, style] of tiers) {
        const base = t[key];
        const solidCss = fillColor(base, style);
        const solidHex = solidHexFor(base, style, m.theme);
        out[colorVar] = base;
        out[`--ts-${key}-deep`] = withOpacity(solidCss, style);
        out[`--hl-${key}-ink`] = inkColor(solidHex, base, style);
        out[`--hl-${key}-idle`] = idleInk(base, style, m.theme);
        out[`--hl-${key}-track`] = trackColor(base, solidCss, m);
    }

    if (m.theme === 'light') Object.assign(out, LIGHT_SURFACE);
    return out;
}

/** The legible (band-clamped) accent for the footer/teleprompter chrome, using
 *  the model's band so the chrome tracks the same clamp as the cells. */
export function legibleForModel(accentHex: string, m: HighlightModel): string {
    return legibleAccentCfg(accentHex, m.bandMinL, m.bandMaxL);
}
