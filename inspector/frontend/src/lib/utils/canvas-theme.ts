/**
 * Canvas colour resolver — the bridge between the CSS token system and the 2D
 * canvases (waveforms, stats charts) that a `data-theme` attribute flip can't
 * reach, because `ctx.fillStyle = '#abc'` is baked into JS, not resolved from
 * the cascade.
 *
 * Each draw module asks for a token by name; we read it once per theme from
 * `getComputedStyle(document.documentElement)` and cache it. The cache is
 * cleared on the `themechange` event (fired by the theme store) so the next
 * redraw picks up the light/dark value. Canvas components listen for the same
 * event to trigger that redraw.
 */

import { THEME_CHANGE_EVENT } from '../stores/theme.svelte';

let cache: Record<string, string> = {};
let installed = false;

function ensureListener(): void {
    if (installed || typeof window === 'undefined') return;
    installed = true;
    window.addEventListener(THEME_CHANGE_EVENT, () => {
        cache = {};
    });
}

/**
 * Resolve a CSS custom property (e.g. '--wf-bg') to its current computed value,
 * cached per theme. `fallback` is returned when the DOM/var is unavailable
 * (SSR, a typo'd token) so a caller always gets a paintable colour.
 */
export function themeColor(token: string, fallback = '#000'): string {
    ensureListener();
    if (cache[token] !== undefined) return cache[token];
    if (typeof document === 'undefined') return fallback;
    const v = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
    const resolved = v || fallback;
    cache[token] = resolved;
    return resolved;
}

/** Resolve several tokens at once into a `{ token: value }` map. */
export function themeColors<T extends Record<string, string>>(tokens: T): Record<keyof T, string> {
    const out = {} as Record<keyof T, string>;
    for (const k in tokens) {
        const token = tokens[k];
        if (token !== undefined) out[k] = themeColor(token);
    }
    return out;
}

/** Drop the cache manually (e.g. after a programmatic token mutation in tests). */
export function clearThemeColorCache(): void {
    cache = {};
}
