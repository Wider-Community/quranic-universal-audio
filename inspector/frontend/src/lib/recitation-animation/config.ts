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
    /** Color of non-active text (reached + unreached words, the ۝ marker). */
    baseColor: string;
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

// Locked baseline tuned in the prototype. The dashboard surface reads this as
// its starting point. Five values stay user-tunable on the dashboard via
// CustomizePanel (motion, granularity, highlightColor, unreachedOpacity,
// fontSizePx); the rest are fixed.
export const DEFAULT_RECITATION_CONFIG: RecitationAnimConfig = {
    wordRevealMs: 600,
    charRevealMs: 80,
    clearFadeMs: 600,
    leadMs: 0,

    easing: 'cubic-bezier(0.25, 1, 0.5, 1)', // ease-out quart (never linear)

    highlightColor: '#4abad9',
    baseColor: '#e1e4e5',
    reachedOpacity: 0.8,
    unreachedOpacity: 0.2,
    wordActiveEmphasisMs: 210,
    charActiveEmphasisMs: 0,
    activeScale: 1.05,
    activeGlowPx: 5,
    activeStrokePx: 0,
    activeStrokeColor: '#000000',
    baseStrokePx: 1.5,
    baseStrokeColor: '#000000',

    // Matches the timestamps-tab animation: the dataset's display text is
    // DigitalKhatt-encoded, so it must render in the DigitalKhatt webfont
    // (@font-face in styles/base.css → /fonts/DigitalKhattV2.otf). Fallbacks
    // are other naskh faces for when the font hasn't loaded.
    fontFamily: "'DigitalKhatt', 'Traditional Arabic', 'Scheherazade New', 'Amiri', serif",
    fontSizePx: 26,
    lineHeight: 2,
    wordSpacingPx: 8,
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
    filmstripProportional: 1,
    filmstripMinCellPx: 30,
    filmstripMaxCellPx: 170,
    filmstripGapPx: 5,
    filmstripHeightPx: 36,
};

/** 8-direction text-shadow that outlines the rendered text *silhouette*. Unlike
 *  per-glyph `-webkit-text-stroke` (which traces each letter and shows seams
 *  where Arabic letters join), this outlines the word's outer border. '' when
 *  width ≤ 0. */
function outlineShadow(px: number, color: string): string {
    if (!px || px <= 0) return '';
    const o = `${px}px`;
    const n = `-${px}px`;
    return [
        `${o} 0 0 ${color}`, `${n} 0 0 ${color}`,
        `0 ${o} 0 ${color}`, `0 ${n} 0 ${color}`,
        `${o} ${o} 0 ${color}`, `${n} ${o} 0 ${color}`,
        `${o} ${n} 0 ${color}`, `${n} ${n} 0 ${color}`,
    ].join(', ');
}

/** Project the line-animation slice of config to CSS custom properties.
 *  The active-unit effects (emphasis/scale/glow) resolve to the *current*
 *  granularity's value, so the same CSS rules render word- or char-tuned. */
export function cssVars(cfg: RecitationAnimConfig): Record<string, string> {
    const isChar = cfg.granularity === 'char';
    const baseOutline = outlineShadow(cfg.baseStrokePx, cfg.baseStrokeColor);
    const activeOutline = cfg.activeStrokePx > 0
        ? outlineShadow(cfg.activeStrokePx, cfg.activeStrokeColor)
        : baseOutline;
    const glow = cfg.activeGlowPx > 0 ? `0 0 ${cfg.activeGlowPx}px ${cfg.highlightColor}` : '';
    // Vertical headroom so an active word scaled by `activeScale` (>1) isn't
    // clipped by the fixed-height, overflow-hidden line box. Round up to a
    // whole px; 0 when no scale.
    const scalePad = Math.ceil(Math.max(0, cfg.activeScale - 1) * cfg.fontSizePx);
    return {
        '--ra-word-reveal': `${cfg.wordRevealMs}ms`,
        '--ra-char-reveal': `${cfg.charRevealMs}ms`,
        '--ra-active-emphasis': `${isChar ? cfg.charActiveEmphasisMs : cfg.wordActiveEmphasisMs}ms`,
        '--ra-clear-fade': `${cfg.clearFadeMs}ms`,
        '--ra-easing': cfg.easing,
        '--ra-highlight': cfg.highlightColor,
        '--ra-base-color': cfg.baseColor,
        '--ra-reached-opacity': String(cfg.reachedOpacity),
        '--ra-unreached-opacity': String(cfg.unreachedOpacity),
        '--ra-active-scale': String(cfg.activeScale),
        '--ra-scale-pad': `${scalePad}px`,
        // Word-silhouette outline (base) + active outline/glow, as text-shadow.
        '--ra-word-shadow': baseOutline || 'none',
        '--ra-word-shadow-active': [glow, activeOutline].filter(Boolean).join(', ') || 'none',
        // Glow-only (no outline) — used by the active CHAR in char granularity so
        // the active letter glows without re-stroking each glyph (the legibility
        // stroke stays on the word silhouette in char mode).
        '--ra-glow': glow || 'none',
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

