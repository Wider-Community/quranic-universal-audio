/**
 * Set of in-flight undo target ids — batch-ids, op-ids, and chain-keys.
 *
 * History cards read this store reactively so their "Undoing…" state
 * survives Svelte's `{#each}` remounts (e.g. when the surrounding store
 * is replaced and a revert-badge sibling appears). Previously the undo
 * handler mutated the original `<button>` element imperatively, which
 * left it stuck on "Undoing…" whenever the card was remounted under it.
 */

import { writable } from 'svelte/store';

export const undoPending = writable<Set<string>>(new Set());

export function markUndoing(id: string): void {
    undoPending.update((s) => {
        if (s.has(id)) return s;
        const next = new Set(s);
        next.add(id);
        return next;
    });
}

export function clearUndoing(id: string): void {
    undoPending.update((s) => {
        if (!s.has(id)) return s;
        const next = new Set(s);
        next.delete(id);
        return next;
    });
}
