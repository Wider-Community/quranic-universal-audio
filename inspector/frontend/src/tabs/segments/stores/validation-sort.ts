/**
 * Validation-accordion sort preferences — user-chosen, localStorage-backed.
 *
 * Holds the active (kind, dir) per accordion category on top of the registry
 * defaults (`IssueDefinition.sorts`). Persisted GLOBALLY (not per-reciter),
 * matching the keyboard-shortcuts / TS-prefs pattern. `resolveSort` falls back
 * to the registry default and rejects a stored kind no longer offered by the
 * category, so a registry change can't strand a stale preference.
 */

import { writable } from 'svelte/store';

import { LS_KEYS } from '../../../lib/utils/constants';
import { IssueRegistry } from '../domain/registry';
import { defaultOption, SORT_META, type SortDir, type SortKind } from '../domain/sorting';

export interface SortPref {
    kind: SortKind;
    dir: SortDir;
}
export type SortPrefs = Record<string, SortPref>;

const KEY = LS_KEYS.SEG_VAL_SORTS;

/** True iff `kind` is a sort the category currently offers. */
function isOffered(category: string, kind: unknown): kind is SortKind {
    return !!IssueRegistry[category]?.sorts?.some((o) => o.kind === kind);
}

function load(): SortPrefs {
    if (typeof localStorage === 'undefined') return {};
    try {
        const raw = localStorage.getItem(KEY);
        if (!raw) return {};
        const parsed = JSON.parse(raw) as Record<string, unknown>;
        const out: SortPrefs = {};
        for (const [cat, val] of Object.entries(parsed)) {
            const v = val as { kind?: unknown; dir?: unknown } | null;
            if (!v || !isOffered(cat, v.kind)) continue;
            const dir: SortDir = v.dir === 'desc' ? 'desc' : 'asc';
            out[cat] = { kind: v.kind, dir };
        }
        return out;
    } catch {
        return {};
    }
}

function persist(p: SortPrefs): void {
    if (typeof localStorage === 'undefined') return;
    try {
        localStorage.setItem(KEY, JSON.stringify(p));
    } catch {
        /* quota / private-mode — non-fatal */
    }
}

/** Active sort prefs by category. Subscribe in components for reactivity. */
export const valSortPrefs = writable<SortPrefs>(load());
valSortPrefs.subscribe(persist);

/**
 * Resolve the effective sort for a category: the stored preference if it's
 * still a valid option, else the registry default. Returns null when the
 * category offers no sorts (e.g. Missing Verses). Pure — pass `$valSortPrefs`.
 */
export function resolveSort(prefs: SortPrefs, category: string): SortPref | null {
    const opts = IssueRegistry[category]?.sorts;
    const def = defaultOption(opts);
    if (!def) return null;
    const stored = prefs[category];
    if (stored && isOffered(category, stored.kind)) return stored;
    return { kind: def.kind, dir: SORT_META[def.kind].defaultDir };
}

/** Make `kind` the active sort for `category`, at its default direction. */
export function selectSort(category: string, kind: SortKind): void {
    valSortPrefs.update((p) => ({ ...p, [category]: { kind, dir: SORT_META[kind].defaultDir } }));
}

/** Flip the active sort's direction for `category` (re-click on the active pill). */
export function toggleDir(category: string): void {
    valSortPrefs.update((p) => {
        const cur = resolveSort(p, category);
        if (!cur) return p;
        return { ...p, [category]: { kind: cur.kind, dir: cur.dir === 'asc' ? 'desc' : 'asc' } };
    });
}
