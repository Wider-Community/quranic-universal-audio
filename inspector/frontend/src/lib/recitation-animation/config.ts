/**
 * Recitation-animation config — the lock target for the throwaway playground.
 *
 * Tunable surface (timing, easing, effects, typography, behaviour, markers).
 * The playground binds a writable copy of `DEFAULT_RECITATION_CONFIG` to live
 * controls; once a look is locked, the exported defaults are edited to the
 * chosen values and the components read them statically. Values project to
 * CSS custom properties via `cssVars()` so the hot path is pure CSS
 * transitions (no per-frame JS style writes beyond opacity).
 *
 * Defaults are grounded in `styles/tokens.css` (`--accent`, `--ease-out-*`,
 * `--t-*`) so the section blends with the live dark theme.
 */

import { writable } from 'svelte/store';

export type Granularity = 'word' | 'char';
export type FilmstripMotion = 'hybrid' | 'tuner' | 'snap';

export interface RecitationAnimConfig {
    // ---- timing (ms) ----
    /** Opacity reveal duration for a word in word granularity. */
    wordRevealMs: number;
    /** Opacity reveal duration for a character in char granularity. */
    charRevealMs: number;
    /** Fade-out duration when a page clears (overflow or ayah end). */
    clearFadeMs: number;
    /** Light a unit this many ms before its true start (negative = lag). */
    leadMs: number;

    // ---- easing ----
    /** CSS easing function applied to reveal + emphasis transitions. */
    easing: string;

    // ---- effects ----
    /** Color of the currently-active word/char. */
    highlightColor: string;
    /** Opacity of already-recited units (0..1). */
    reachedOpacity: number;
    /** Opacity of not-yet-reached units (0..1). */
    unreachedOpacity: number;
    /** Active-highlight transition duration (color/scale/glow/stroke), split by
     *  granularity — chars are smaller + stream faster than words, so they
     *  usually want a quicker emphasis. The active granularity's value drives
     *  `--ra-active-emphasis`. */
    wordActiveEmphasisMs: number;
    charActiveEmphasisMs: number;
    /** Scale transform on the active unit (1 = none). Word granularity only —
     *  inline Arabic chars can't transform without breaking cursive joining. */
    activeScale: number;
    /** Glow (text-shadow blur px) on the active unit (0 = none). */
    activeGlowPx: number;
    /** Outline (text-stroke) on the ACTIVE unit — makes the current word/char
     *  pop. Width px + color; 0 = off. Painted behind the fill (paint-order). */
    activeStrokePx: number;
    activeStrokeColor: string;
    /** Outline (text-stroke) on ALL line text — aids legibility + separation of
     *  crowded short ayahs against the background. Width px + color; 0 = off. */
    baseStrokePx: number;
    baseStrokeColor: string;

    // ---- typography ----
    fontFamily: string;
    fontSizePx: number;
    lineHeight: number;
    wordSpacingPx: number;
    letterSpacingPx: number;

    // ---- behaviour ----
    granularity: Granularity;
    /** Clear + re-page when the active word would overflow the line. */
    clearOnOverflow: boolean;
    /** Clear + restart from word 1 when the ayah changes. */
    clearOnAyahEnd: boolean;
    /** Center the fitted line (vs right-aligned RTL fill). */
    centerLine: boolean;
    /** Append the ۝ end-of-ayah marker (Arabic-Indic numeral) after each ayah. */
    showAyahMarker: boolean;

    // ---- section chrome ----
    autoExpandOnPlay: boolean;
    collapsedByDefault: boolean;

    // ---- ayah filmstrip (center-anchored nav strip above the bar) ----
    filmstripShow: boolean;
    /** Motion model: `hybrid` (continuous tuner-center, drag snaps to ayah),
     *  `tuner` (continuous, drag scrubs exact time), `snap` (center on ayah
     *  change only, drag = carousel snap). */
    filmstripMotion: FilmstripMotion;
    /** 0 = all cells equal (min width); 1 = fully duration-proportional. */
    filmstripProportional: number;
    /** Min cell width (px) — must fit the widest verse number. */
    filmstripMinCellPx: number;
    /** Max cell width (px) — caps long ayahs. */
    filmstripMaxCellPx: number;
    /** Gap between cells (px). */
    filmstripGapPx: number;
    /** Strip height (px). */
    filmstripHeightPx: number;
}

/** Easing presets offered in the playground (ease-out only — no bounce). */
export const EASING_OPTIONS: { label: string; value: string }[] = [
    { label: 'Out · quart', value: 'cubic-bezier(0.25, 1, 0.5, 1)' },
    { label: 'Out · expo', value: 'cubic-bezier(0.16, 1, 0.3, 1)' },
    { label: 'Out · cubic', value: 'cubic-bezier(0.33, 1, 0.68, 1)' },
    { label: 'Linear', value: 'linear' },
];

/** Filmstrip motion models offered in the playground. */
export const FILMSTRIP_MOTIONS: { label: string; value: FilmstripMotion }[] = [
    { label: 'Hybrid', value: 'hybrid' },
    { label: 'Tuner', value: 'tuner' },
    { label: 'Snap', value: 'snap' },
];

export const DEFAULT_RECITATION_CONFIG: RecitationAnimConfig = {
    wordRevealMs: 260,
    charRevealMs: 140,
    clearFadeMs: 220,
    leadMs: 0,

    easing: 'cubic-bezier(0.25, 1, 0.5, 1)',

    highlightColor: 'var(--accent)',
    reachedOpacity: 0.62,
    unreachedOpacity: 0,
    wordActiveEmphasisMs: 180,
    charActiveEmphasisMs: 110,
    activeScale: 1,
    activeGlowPx: 0,
    activeStrokePx: 0,
    activeStrokeColor: 'var(--accent)',
    baseStrokePx: 0.35,
    baseStrokeColor: 'oklch(0.13 0.03 285 / 0.7)',

    // Matches the timestamps-tab animation: the dataset's display text is
    // DigitalKhatt-encoded, so it must render in the DigitalKhatt webfont
    // (@font-face in styles/base.css → /fonts/DigitalKhattV2.otf). Fallbacks
    // are other naskh faces for when the font hasn't loaded.
    fontFamily: "'DigitalKhatt', 'Traditional Arabic', 'Scheherazade New', 'Amiri', serif",
    fontSizePx: 34,
    lineHeight: 1.9,
    wordSpacingPx: 5,
    letterSpacingPx: 0,

    granularity: 'word',
    clearOnOverflow: true,
    clearOnAyahEnd: true,
    centerLine: true,
    showAyahMarker: true,

    autoExpandOnPlay: true,
    collapsedByDefault: false,

    filmstripShow: true,
    filmstripMotion: 'hybrid',
    filmstripProportional: 0.7,
    filmstripMinCellPx: 40,
    filmstripMaxCellPx: 120,
    filmstripGapPx: 4,
    filmstripHeightPx: 40,
};

/** Project the line-animation slice of config to CSS custom properties.
 *  The active-unit effects (emphasis/scale/glow) resolve to the *current*
 *  granularity's value, so the same CSS rules render word- or char-tuned. */
export function cssVars(cfg: RecitationAnimConfig): Record<string, string> {
    const isChar = cfg.granularity === 'char';
    return {
        '--ra-word-reveal': `${cfg.wordRevealMs}ms`,
        '--ra-char-reveal': `${cfg.charRevealMs}ms`,
        '--ra-active-emphasis': `${isChar ? cfg.charActiveEmphasisMs : cfg.wordActiveEmphasisMs}ms`,
        '--ra-clear-fade': `${cfg.clearFadeMs}ms`,
        '--ra-easing': cfg.easing,
        '--ra-highlight': cfg.highlightColor,
        '--ra-reached-opacity': String(cfg.reachedOpacity),
        '--ra-unreached-opacity': String(cfg.unreachedOpacity),
        '--ra-active-scale': String(cfg.activeScale),
        '--ra-active-glow': `${cfg.activeGlowPx}px`,
        '--ra-active-stroke': `${cfg.activeStrokePx}px`,
        '--ra-active-stroke-color': cfg.activeStrokeColor,
        '--ra-base-stroke': `${cfg.baseStrokePx}px`,
        '--ra-base-stroke-color': cfg.baseStrokeColor,
        '--ra-font': cfg.fontFamily,
        '--ra-font-size': `${cfg.fontSizePx}px`,
        '--ra-line-height': String(cfg.lineHeight),
        '--ra-word-spacing': `${cfg.wordSpacingPx}px`,
        '--ra-letter-spacing': `${cfg.letterSpacingPx}px`,
        '--ra-align': cfg.centerLine ? 'center' : 'right',
    };
}

/** Serialize a config object into the `cssText` of inline custom properties. */
export function cssVarText(cfg: RecitationAnimConfig): string {
    return Object.entries(cssVars(cfg))
        .map(([k, v]) => `${k}: ${v}`)
        .join('; ');
}

/** Writable config store — used by the playground (live binding) and as a
 *  convenience for any surface that wants reactive config. Surfaces that just
 *  consume locked values should import `DEFAULT_RECITATION_CONFIG` directly. */
export const recitationConfig = writable<RecitationAnimConfig>({
    ...DEFAULT_RECITATION_CONFIG,
});
