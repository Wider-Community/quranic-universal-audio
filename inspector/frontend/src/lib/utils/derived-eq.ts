/**
 * Equality-gated derived store.
 *
 * Svelte 4's built-in `derived` fires downstream subscribers on EVERY source
 * update regardless of whether the derived value changed. That defeats the
 * purpose of consolidating multiple fields into a single underlying state
 * store — subscribers to any one field would re-fire on every mutation of
 * any other field.
 *
 * `derivedEq` wraps `readable` + manual subscription, caching the last
 * selector result and skipping `set()` when the new value is `===` the
 * cached one (identity comparison). Use this to expose atomic fields out of
 * a bundled state store without fan-out.
 *
 * Example:
 *   const _state = writable({ mode: null, uid: null });
 *   export const mode = derivedEq(_state, ($s) => $s.mode);
 *   export const uid  = derivedEq(_state, ($s) => $s.uid);
 *
 * Both `mode` and `uid` keep the `$mode` / `$uid` auto-subscription semantics
 * in Svelte components, but a write to `_state` that changes only `uid` will
 * not notify `mode` subscribers.
 */

import type { Readable } from 'svelte/store';
import { get, readable } from 'svelte/store';

export function derivedEq<S, T>(
    src: Readable<S>,
    fn: (s: S) => T,
): Readable<T> {
    return readable(fn(get(src)), (set) => {
        // Force the first emission through so the readable's internal value is
        // synced with the source AT SUBSCRIBE TIME. Otherwise, if the source
        // changed while no one was subscribed (e.g. `get()` on a store with no
        // Svelte component subscribers), the readable's value is stuck on its
        // module-load `initial` and `get()` returns that instead of the
        // current source-derived value.
        let last: T;
        let primed = false;
        return src.subscribe((v) => {
            const next = fn(v);
            if (!primed || next !== last) {
                primed = true;
                last = next;
                set(next);
            }
        });
    });
}
