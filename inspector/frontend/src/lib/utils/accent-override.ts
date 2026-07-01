/**
 * Remap the theme accent family to the user's highlight colour for a subtree.
 *
 * The footer / player / filmstrip chrome (play button, progress, footer toggle
 * on-states, bookmark, filmstrip cells / needle / fill / number, picker hovers,
 * focus rings) all consume the `--accent*` tokens from `styles/tokens.css`.
 * Setting these vars on a container re-derives them from the chosen colour, so
 * the whole subtree recolours from the fixed cyan accent to the user's
 * highlight (the footer droplet) with no per-element edits.
 *
 * Scope is deliberately the footer containers (`.now-reciting`, `.player`), so
 * the rest of the app keeps the cyan accent. The verse marker is excluded for
 * free: it reads `--ra-base-color`, not `--accent`, so it stays its base ink.
 *
 * Tints mirror tokens.css (tint 14% / tint-soft 7% / strong = oklab lighten);
 * `--accent-fg` (ink on a filled accent, e.g. the play glyph) is the WCAG
 * auto-contrast pick so it stays legible on any chosen colour.
 */
import { inkFor, legibleAccent, legibleAccentCfg } from './color-derive';
import type { Theme } from './highlight-model';

// On light paper the footer/player chrome paints the accent on a near-white bg,
// so the legibility clamp must pull a too-LIGHT pick DOWN into a darker band
// (the dark theme lifts a too-DARK pick up instead). Hover lightens on dark,
// darkens on light.
const LIGHT_BAND_MIN_L = 0.46;
const LIGHT_BAND_MAX_L = 0.70;

export function accentVars(hex: string, theme: Theme = 'dark'): Record<string, string> {
    // The footer/filmstrip chrome paints the accent directly on the page bg, so a
    // pick outside the legible band is clamped first (in-band picks kept verbatim).
    // Tints + ink derive from the legible colour so they track it.
    const isLight = theme === 'light';
    const a = isLight ? legibleAccentCfg(hex, LIGHT_BAND_MIN_L, LIGHT_BAND_MAX_L) : legibleAccent(hex);
    return {
        '--accent': a,
        '--accent-strong': `color-mix(in oklab, ${a} 85%, ${isLight ? 'black' : 'white'})`,
        '--accent-tint': `color-mix(in srgb, ${a} 14%, transparent)`,
        '--accent-tint-soft': `color-mix(in srgb, ${a} 7%, transparent)`,
        '--accent-fg': inkFor(a),
    };
}

/** The override as inline `cssText` for a `style={...}` binding. */
export function accentVarText(hex: string, theme: Theme = 'dark'): string {
    return Object.entries(accentVars(hex, theme))
        .map(([k, v]) => `${k}: ${v}`)
        .join('; ');
}
