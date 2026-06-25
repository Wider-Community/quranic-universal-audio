/**
 * Reactive locale state for the SPA (Svelte 5 runes).
 *
 * Paraglide message functions read the *ambient* locale set by `setLocale()`
 * from `$lib/paraglide/runtime`. This module mirrors that ambient locale into a
 * `$state` cell so runes components re-render on switch: reading `i18n.locale`
 * inside a template / `$derived` registers a dependency, and the `_locale`
 * write on switch trips it.
 *
 * Switching is funnelled through `switchLocale()` in `./locale-store.ts`, the
 * single entry point that updates Paraglide's ambient locale, the legacy store
 * mirror, this runes cell, and <html dir/lang> — keeping runes and legacy files
 * in lockstep. Persistence is owned by Paraglide (the `localStorage` strategy +
 * the `insp_locale` key on `paraglideVitePlugin`); this module never touches
 * localStorage directly.
 */
import { baseLocale, getLocale, locales } from '$lib/paraglide/runtime';

import { registerRuneSetter, switchLocale } from './locale-store';

export type Locale = (typeof locales)[number];

// Seed from Paraglide's own resolution (localStorage → preferredLanguage → baseLocale).
let _locale = $state<Locale>(getLocale());

// Let the shared switcher trip this runes cell without a .ts→.svelte.ts import.
registerRuneSetter((loc) => {
    _locale = loc as Locale;
});

const RTL: ReadonlySet<string> = new Set(['ar']);

function applyDocument(loc: Locale): void {
    const el = document.documentElement;
    el.lang = loc;
    el.dir = RTL.has(loc) ? 'rtl' : 'ltr';
}

export const i18n = {
    /** Reactive current locale — read in components / `$derived`. */
    get locale(): Locale {
        return _locale;
    },
    get locales(): readonly Locale[] {
        return locales;
    },
    get baseLocale(): Locale {
        return baseLocale;
    },
    /**
     * Switch locale in-place (no reload). Delegates to the shared `switchLocale`,
     * which persists via the localStorage strategy under key "insp_locale" and
     * updates <html dir/lang>.
     */
    set(loc: Locale): void {
        if (loc === _locale) return;
        switchLocale(loc);
    },
};

/** Call once at app boot (main.ts) to sync <html dir/lang> with the resolved locale. */
export function initLocale(): void {
    applyDocument(_locale);
}
