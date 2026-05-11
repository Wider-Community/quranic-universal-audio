/**
 * Single global gate for every edit affordance in the SPA.
 *
 * The `kind` enum mirrors the v2 role schema (anonymous /
 * contributor-with-claim / maintainer / owner). `view` is the union of
 * "anonymous" and "logged-in but no claim on this reciter".
 *
 * Phase 2 always emits `{kind: 'view', viewReason: 'unauthenticated'}`.
 * Phase 3 wires session state and starts emitting `editor`/`maintainer`/
 * `owner` per the active reciter's claim + the user's role.
 *
 * Components don't read this directly; they apply the `editGate` Svelte
 * action to any element that triggers an edit. The action consumes this
 * store and either passes the click through or shows
 * `EditAffordancePopover` anchored to the element.
 */

import { derived, writable } from 'svelte/store';

export type EditingKind = 'view' | 'editor' | 'maintainer' | 'owner';

export type ViewReason =
    | 'unauthenticated'   // not logged in
    | 'wrong-assignee'    // logged in, but another contributor holds the claim
    | 'completed'         // reciter is in published terminal state
    | 'discarded';        // reciter is admin-soft-deleted (Phase 7)

export interface EditingMode {
    kind: EditingKind;
    /** Populated only when `kind === 'view'`. Drives popover copy. */
    viewReason?: ViewReason;
}

/** Single source of truth for the "can the current user edit?" check. */
export const editingMode = writable<EditingMode>({
    kind: 'view',
    viewReason: 'unauthenticated',
});

/** True when no edit affordance should be live for the current user. */
export const editingDisabled = derived(editingMode, (m) => m.kind === 'view');

/** True when the current user has any admin role (maintainer | owner). */
export const isAdmin = derived(
    editingMode,
    (m) => m.kind === 'maintainer' || m.kind === 'owner',
);

/** Helper for tests / Phase 3 callers — replace the whole mode in one call. */
export function setEditingMode(mode: EditingMode): void {
    editingMode.set(mode);
}
