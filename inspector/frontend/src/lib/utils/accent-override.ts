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
import { inkFor } from './color-derive';

export function accentVars(hex: string): Record<string, string> {
    return {
        '--accent': hex,
        '--accent-strong': `color-mix(in oklab, ${hex} 85%, white)`,
        '--accent-tint': `color-mix(in srgb, ${hex} 14%, transparent)`,
        '--accent-tint-soft': `color-mix(in srgb, ${hex} 7%, transparent)`,
        '--accent-fg': inkFor(hex),
    };
}

/** The override as inline `cssText` for a `style={...}` binding. */
export function accentVarText(hex: string): string {
    return Object.entries(accentVars(hex))
        .map(([k, v]) => `${k}: ${v}`)
        .join('; ');
}
