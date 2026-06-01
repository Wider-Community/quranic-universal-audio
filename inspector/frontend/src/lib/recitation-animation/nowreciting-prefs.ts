/**
 * localStorage persistence for the dashboard now-reciting section.
 *
 * Caches the full `RecitationAnimConfig` (only five fields are user-editable,
 * but persisting the whole object is forward-compatible if more are exposed)
 * plus the section collapse state. Stored values are merged over
 * `DEFAULT_RECITATION_CONFIG` on load so a baseline change (new locked default)
 * still wins for any field the user never touched, and missing fields never go
 * undefined.
 */

import { DEFAULT_RECITATION_CONFIG, type RecitationAnimConfig } from './config';

const KEY = 'nowreciting-prefs';

export interface NowRecitingPrefs {
    config: RecitationAnimConfig;
    /** true = collapsed, false = expanded, null = no explicit choice yet
     *  (→ default expanded for a published selection). */
    collapsed: boolean | null;
}

export function loadPrefs(): NowRecitingPrefs {
    const base: NowRecitingPrefs = {
        config: { ...DEFAULT_RECITATION_CONFIG },
        collapsed: null,
    };
    if (typeof localStorage === 'undefined') return base;
    try {
        const raw = localStorage.getItem(KEY);
        if (!raw) return base;
        const parsed = JSON.parse(raw) as {
            config?: Partial<RecitationAnimConfig>;
            collapsed?: unknown;
        };
        return {
            config: { ...DEFAULT_RECITATION_CONFIG, ...(parsed.config ?? {}) },
            collapsed: typeof parsed.collapsed === 'boolean' ? parsed.collapsed : null,
        };
    } catch {
        return base;
    }
}

export function savePrefs(prefs: NowRecitingPrefs): void {
    if (typeof localStorage === 'undefined') return;
    try {
        localStorage.setItem(
            KEY,
            JSON.stringify({ config: prefs.config, collapsed: prefs.collapsed }),
        );
    } catch {
        /* quota / private-mode — non-fatal */
    }
}
