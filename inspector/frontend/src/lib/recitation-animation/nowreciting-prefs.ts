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

import {
    DEFAULT_RECITATION_CONFIG,
    type Granularity,
    type RecitationAnimConfig,
} from './config';

const KEY = 'nowreciting-prefs';

export interface NowRecitingPrefs {
    config: RecitationAnimConfig;
    unreachedOpacityByGranularity: Record<Granularity, number>;
    silentOmit: boolean;
    /** true = collapsed, false = expanded, null = no explicit choice yet
     *  (→ default expanded for a published selection). */
    collapsed: boolean | null;
}

function migratedOpacity(value: unknown, fallback: number): number {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1) {
        return fallback;
    }
    return Math.abs(value - 0.8) < 0.001 ? 1 : value;
}

export function loadPrefs(): NowRecitingPrefs {
    const base: NowRecitingPrefs = {
        config: { ...DEFAULT_RECITATION_CONFIG },
        unreachedOpacityByGranularity: {
            word: DEFAULT_RECITATION_CONFIG.unreachedOpacity,
            char: DEFAULT_RECITATION_CONFIG.unreachedOpacity,
        },
        silentOmit: false,
        collapsed: null,
    };
    if (typeof localStorage === 'undefined') return base;
    try {
        const raw = localStorage.getItem(KEY);
        if (!raw) return base;
        const parsed = JSON.parse(raw) as {
            config?: Partial<RecitationAnimConfig>;
            unreachedOpacityByGranularity?: Partial<Record<Granularity, number>>;
            silentOmit?: unknown;
            collapsed?: unknown;
        };
        const config = { ...DEFAULT_RECITATION_CONFIG, ...(parsed.config ?? {}) };
        config.granularity = config.granularity === 'char' ? 'char' : 'word';
        // Until v13's shared-text animation, the UI's "full" preset was 0.8.
        // Migrate that discrete persisted preset to literal full opacity so
        // future and already-recited words have identical base paint.
        const legacyOpacity = migratedOpacity(
            config.unreachedOpacity,
            DEFAULT_RECITATION_CONFIG.unreachedOpacity,
        );
        const storedOpacity = parsed.unreachedOpacityByGranularity;
        const unreachedOpacityByGranularity = {
            word: migratedOpacity(storedOpacity?.word, legacyOpacity),
            char: migratedOpacity(storedOpacity?.char, legacyOpacity),
        };
        config.unreachedOpacity = unreachedOpacityByGranularity[config.granularity];
        return {
            config,
            unreachedOpacityByGranularity,
            silentOmit: parsed.silentOmit === true,
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
            JSON.stringify({
                config: prefs.config,
                unreachedOpacityByGranularity: prefs.unreachedOpacityByGranularity,
                silentOmit: prefs.silentOmit,
                collapsed: prefs.collapsed,
            }),
        );
    } catch {
        /* quota / private-mode — non-fatal */
    }
}
