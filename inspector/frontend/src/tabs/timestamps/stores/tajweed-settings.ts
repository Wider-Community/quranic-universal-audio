/**
 * Per-rule tajweed display settings for the Timestamps analysis row — an enable
 * toggle + an optional colour override per legend rule, cached in localStorage and
 * applied live. Mirrors the bookmarks store (init-from-LS + explicit persist on
 * mutation); colour overrides are written to the `--tj-*` custom properties on the
 * document root so both the legend swatches and the per-cell underlines recolour
 * with no re-render. The enable toggles drive `tjShadow` filtering in
 * `TimedAnalysisRow` (reactive on the store), so disabling a rule clears its bar.
 *
 * Defaults come from the rule registry (`tajweed-rules.ts`): everything on except
 * iẓhar and madd ṭabīʿī.
 */
import { writable } from 'svelte/store';

import { LS_KEYS } from '../../../lib/utils/constants';
import { DEFAULT_ENABLED, LEGEND, LEGEND_KEYS, legendRows } from '../utils/tajweed-rules';

export interface RuleSetting {
    enabled: boolean;
    /** hex override (`#rrggbb`) or null to use the registry/CSS default. */
    color: string | null;
}
export type TajweedSettings = Record<string, RuleSetting>;

/** legendKey → its backing `--tj-*` custom property (for colour overrides). */
const COLOR_VAR: Record<string, string> = Object.fromEntries(
    LEGEND.flatMap((g) => legendRows(g).map((r) => [r.legendKey, r.colorVar])),
);

function defaults(): TajweedSettings {
    return Object.fromEntries(
        LEGEND_KEYS.map((k) => [k, { enabled: DEFAULT_ENABLED[k] ?? true, color: null }]),
    );
}

function load(): TajweedSettings {
    const base = defaults();
    try {
        const raw = localStorage.getItem(LS_KEYS.TS_TAJWEED);
        if (raw) {
            const parsed = JSON.parse(raw) as Partial<TajweedSettings>;
            for (const k of LEGEND_KEYS) {
                const r = parsed?.[k];
                if (!r) continue;
                if (typeof r.enabled === 'boolean') base[k]!.enabled = r.enabled;
                if (typeof r.color === 'string' || r.color === null) base[k]!.color = r.color;
            }
        }
    } catch {
        /* corrupt / unavailable storage — fall back to defaults */
    }
    return base;
}

function persist(s: TajweedSettings): void {
    try {
        localStorage.setItem(LS_KEYS.TS_TAJWEED, JSON.stringify(s));
    } catch {
        /* quota / unavailable — degrade to in-memory */
    }
}

/** Write each rule's colour override to its `--tj-*` var on the document root
 *  (or clear it back to the CSS default when unset). */
function applyColorOverrides(s: TajweedSettings): void {
    if (typeof document === 'undefined') return;
    const root = document.documentElement;
    for (const k of LEGEND_KEYS) {
        const v = COLOR_VAR[k];
        if (!v) continue;
        const c = s[k]?.color ?? null;
        if (c) root.style.setProperty(v, c);
        else root.style.removeProperty(v);
    }
}

export const tajweedSettings = writable<TajweedSettings>(defaults());

/** Hydrate from localStorage and apply colour overrides — call once on tab mount. */
export function initTajweedSettings(): void {
    const s = load();
    tajweedSettings.set(s);
    applyColorOverrides(s);
}

/** Whether a rule's underline is enabled (defaults to on for an unknown key). */
export function isRuleEnabled(s: TajweedSettings, legendKey: string): boolean {
    return s[legendKey]?.enabled ?? true;
}

export function setRuleEnabled(legendKey: string, enabled: boolean): void {
    tajweedSettings.update((s) => {
        const next = { ...s, [legendKey]: { ...s[legendKey]!, enabled } };
        persist(next);
        return next;
    });
}

/** In-session memory of the enabled rules a group had right before it was
 *  group-disabled, keyed by the group's stable id — so re-enabling restores exactly
 *  that set rather than blindly switching every rule on. Not persisted: a quick
 *  convenience that resets with the tab. */
const groupMemory: Record<string, string[]> = {};

/** Whether a group (its set of rule legendKeys) has at least one rule enabled — the
 *  group toggle's on-state, so manually enabling any single rule flips it back on. */
export function isGroupEnabled(s: TajweedSettings, keys: string[]): boolean {
    return keys.some((k) => isRuleEnabled(s, k));
}

/** Quick-toggle a whole group of rules. Disabling snapshots the currently-enabled
 *  members into `groupMemory` then clears them all; enabling restores that snapshot
 *  (or, with no snapshot, switches every member on). */
export function setGroupEnabled(groupId: string, keys: string[], enabled: boolean): void {
    tajweedSettings.update((s) => {
        const next = { ...s };
        if (enabled) {
            const remembered = groupMemory[groupId];
            const restore = remembered && remembered.length ? remembered : keys;
            for (const k of keys) next[k] = { ...s[k]!, enabled: restore.includes(k) };
        } else {
            groupMemory[groupId] = keys.filter((k) => isRuleEnabled(s, k));
            for (const k of keys) next[k] = { ...s[k]!, enabled: false };
        }
        persist(next);
        return next;
    });
}

export function setRuleColor(legendKey: string, color: string | null): void {
    tajweedSettings.update((s) => {
        const next = { ...s, [legendKey]: { ...s[legendKey]!, color } };
        persist(next);
        applyColorOverrides(next);
        return next;
    });
}

/** Restore one rule to its registry defaults (enabled state + no colour override). */
export function resetTajweedRule(legendKey: string): void {
    tajweedSettings.update((s) => {
        const next = {
            ...s,
            [legendKey]: { enabled: DEFAULT_ENABLED[legendKey] ?? true, color: null },
        };
        persist(next);
        applyColorOverrides(next);
        return next;
    });
}

/** Force every rule's underline on transiently (tajweed report mode) WITHOUT
 *  persisting, so all colours are visible while picking targets. Colours are
 *  preserved. Returns the prior settings to hand back to
 *  {@link restoreTajweedSettings} on exit. */
export function forceAllTajweedEnabled(): TajweedSettings {
    let prev: TajweedSettings = {};
    tajweedSettings.update((s) => {
        prev = s;
        return Object.fromEntries(
            LEGEND_KEYS.map((k) => [k, { enabled: true, color: s[k]?.color ?? null }]),
        );
    });
    return prev;
}

/** Restore a snapshot captured by {@link forceAllTajweedEnabled} (no persist —
 *  it already reflects the user's saved settings). */
export function restoreTajweedSettings(snapshot: TajweedSettings): void {
    tajweedSettings.set(snapshot);
}

/** Restore every rule to its registry defaults. */
export function resetAllTajweed(): void {
    const next = defaults();
    tajweedSettings.set(next);
    persist(next);
    applyColorOverrides(next);
}
