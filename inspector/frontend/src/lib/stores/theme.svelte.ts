/**
 * Theme store — the single owner of the light/dark switch.
 *
 * The actual `data-theme` attribute is first set on <html> by the inline script
 * in index.html (flash-free, before first paint). This store reads that as its
 * initial truth (no double-read of localStorage, no flash), then owns every
 * subsequent flip: it updates the `$state`, persists to localStorage, re-sets
 * the attribute (which re-skins all token-driven CSS), and fires a window
 * `themechange` event so the imperative 2D-canvas surfaces (waveforms, charts)
 * — which a CSS attribute flip can't reach — repaint. See
 * lib/utils/canvas-theme.ts for the resolver those canvases read.
 */

import { readable } from 'svelte/store';

import { LS_KEYS } from '../utils/constants';

export type Theme = 'light' | 'dark';

/** The custom event canvas components listen for to repaint on a theme flip. */
export const THEME_CHANGE_EVENT = 'themechange';

function readInitial(): Theme {
    if (typeof document !== 'undefined') {
        const attr = document.documentElement.getAttribute('data-theme');
        if (attr === 'light' || attr === 'dark') return attr;
    }
    return 'dark';
}

class ThemeStore {
    current = $state<Theme>(readInitial());

    get isLight(): boolean {
        return this.current === 'light';
    }

    set(theme: Theme): void {
        if (theme === this.current) return;
        this.current = theme;
        try {
            localStorage.setItem(LS_KEYS.THEME, theme);
        } catch {
            /* quota / private-mode — non-fatal */
        }
        if (typeof document !== 'undefined') {
            document.documentElement.setAttribute('data-theme', theme);
        }
        if (typeof window !== 'undefined') {
            // Let the canvas-theme resolver drop its cache before listeners redraw.
            window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: theme }));
        }
    }

    toggle(): void {
        this.set(this.current === 'light' ? 'dark' : 'light');
    }
}

export const themeStore = new ThemeStore();

/**
 * A `svelte/store` readable mirror of the theme, for legacy ($:/auto-subscribe)
 * components that can't reactively read the runes `themeStore.current`. Updates
 * on the same `themechange` event. Runes components should read `themeStore`
 * directly; this exists only for the legacy bridge (`$theme$`).
 */
export const theme$ = readable<Theme>(readInitial(), (set) => {
    if (typeof window === 'undefined') return;
    const handler = (e: Event): void => {
        const detail = (e as CustomEvent<Theme>).detail;
        set(detail === 'light' || detail === 'dark' ? detail : themeStore.current);
    };
    window.addEventListener(THEME_CHANGE_EVENT, handler);
    return () => window.removeEventListener(THEME_CHANGE_EVENT, handler);
});
