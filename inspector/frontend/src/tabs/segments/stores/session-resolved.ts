/**
 * Session-resolved cards — pure in-memory state for accordion cards that
 * the user has resolved via an edit (not via explicit Ignore).
 *
 * When an edit dispatched from a validation accordion card belongs to a
 * category whose registry entry has `softResolveOnEdit: true`
 * (`boundary_adj`, `audio_bleeding`, `qalqala`, `repetitions`), the
 * dispatcher records `(segment_uid, category)` here so the
 * ValidationPanel hides that card for the rest of the session — even if
 * the post-save validator still flags it. Reloading the page or
 * switching reciter clears the set; if the validator still flags the
 * segment then, the card returns.
 *
 * This is deliberately decoupled from `seg.ignored_categories`. That
 * persisted list reflects ONLY explicit Ignore actions, never edits.
 */

import { writable, get as storeGet } from 'svelte/store';

/** Map of segment_uid → set of category keys soft-resolved this session. */
type SessionResolvedMap = ReadonlyMap<string, ReadonlySet<string>>;

const _store = writable<SessionResolvedMap>(new Map());

/** Subscribe-style read for components that need reactive filtering. */
export const sessionResolvedCards = { subscribe: _store.subscribe };

/**
 * Mark a (uid, category) pair as resolved-this-session. Idempotent.
 * No-op when uid is empty/null.
 */
export function markSessionResolved(uid: string | null | undefined, category: string): void {
    if (!uid) return;
    _store.update((m) => {
        const next = new Map(m);
        const existing = next.get(uid);
        const set = new Set(existing ?? []);
        set.add(category);
        next.set(uid, set);
        return next;
    });
}

/** Returns true when the given (uid, category) was soft-resolved this session. */
export function isSessionResolved(uid: string | null | undefined, category: string): boolean {
    if (!uid) return false;
    const m = storeGet(_store);
    return m.get(uid)?.has(category) ?? false;
}

/**
 * Clear all soft-resolved entries. Call on chapter switch, reciter
 * change, or page reload — whenever the validation panel state should
 * start fresh.
 */
export function clearSessionResolved(): void {
    _store.set(new Map());
}

/**
 * Read-only snapshot for filter helpers. Avoids leaking the writable.
 */
export function getSessionResolvedSnapshot(): SessionResolvedMap {
    return storeGet(_store);
}
