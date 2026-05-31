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

export interface RecitationAnimConfig {
    // ---- timing (ms) ----
    /** Opacity reveal duration for a word in word granularity. */
    wordRevealMs: number;
    /** Opacity reveal duration for a character in char granularity. */
    charRevealMs: number;
    /** Transition duration for the active highlight (color / scale / glow). */
    activeEmphasisMs: number;
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
    /** Scale transform on the active unit (1 = none). */
    activeScale: number;
    /** Glow (text-shadow blur, px) on the active unit (0 = none). */
    activeGlowPx: number;

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

    // ---- section chrome ----
    autoExpandOnPlay: boolean;
    collapsedByDefault: boolean;

    // ---- timeline ayah markers ----
    markersShow: boolean;
    markerColor: string;
    markerWidthPx: number;
    markerHeightPx: number;
    markerOpacity: number;
    markerHoverLabel: boolean;
}

/** Easing presets offered in the playground (ease-out only — no bounce). */
export const EASING_OPTIONS: { label: string; value: string }[] = [
    { label: 'Out · quart', value: 'cubic-bezier(0.25, 1, 0.5, 1)' },
    { label: 'Out · expo', value: 'cubic-bezier(0.16, 1, 0.3, 1)' },
    { label: 'Out · cubic', value: 'cubic-bezier(0.33, 1, 0.68, 1)' },
    { label: 'Linear', value: 'linear' },
];

export const DEFAULT_RECITATION_CONFIG: RecitationAnimConfig = {
    wordRevealMs: 260,
    charRevealMs: 140,
    activeEmphasisMs: 180,
    clearFadeMs: 220,
    leadMs: 0,

    easing: 'cubic-bezier(0.25, 1, 0.5, 1)',

    highlightColor: 'var(--accent)',
    reachedOpacity: 0.62,
    unreachedOpacity: 0,
    activeScale: 1,
    activeGlowPx: 0,

    fontFamily: '"Scheherazade New", "Amiri", "Noto Naskh Arabic", "Traditional Arabic", serif',
    fontSizePx: 34,
    lineHeight: 1.9,
    wordSpacingPx: 0,
    letterSpacingPx: 0,

    granularity: 'word',
    clearOnOverflow: true,
    clearOnAyahEnd: true,

    autoExpandOnPlay: true,
    collapsedByDefault: false,

    markersShow: true,
    markerColor: 'var(--accent)',
    markerWidthPx: 2,
    markerHeightPx: 7,
    markerOpacity: 0.5,
    markerHoverLabel: true,
};

/** Project the line-animation slice of config to CSS custom properties. */
export function cssVars(cfg: RecitationAnimConfig): Record<string, string> {
    return {
        '--ra-word-reveal': `${cfg.wordRevealMs}ms`,
        '--ra-char-reveal': `${cfg.charRevealMs}ms`,
        '--ra-active-emphasis': `${cfg.activeEmphasisMs}ms`,
        '--ra-clear-fade': `${cfg.clearFadeMs}ms`,
        '--ra-easing': cfg.easing,
        '--ra-highlight': cfg.highlightColor,
        '--ra-reached-opacity': String(cfg.reachedOpacity),
        '--ra-unreached-opacity': String(cfg.unreachedOpacity),
        '--ra-active-scale': String(cfg.activeScale),
        '--ra-active-glow': `${cfg.activeGlowPx}px`,
        '--ra-font': cfg.fontFamily,
        '--ra-font-size': `${cfg.fontSizePx}px`,
        '--ra-line-height': String(cfg.lineHeight),
        '--ra-word-spacing': `${cfg.wordSpacingPx}px`,
        '--ra-letter-spacing': `${cfg.letterSpacingPx}px`,
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
