/**
 * Single global gate for every edit affordance in the SPA.
 *
 * The `kind` enum mirrors the role schema (anonymous /
 * contributor-with-claim / maintainer / owner). `view` is the union of
 * "anonymous" and "logged-in but no claim on this reciter".
 *
 * Components don't read this directly; they apply the `editGate` Svelte
 * action to any element that triggers an edit. The action consumes this
 * store and either passes the click through or shows
 * `EditAffordancePopover` anchored to the element.
 */

import { derived, get, writable } from 'svelte/store';

import type { ReciterTask } from '../api/reciter-task';
import type { CurrentUser } from './current-user';

export type EditingKind = 'view' | 'editor' | 'maintainer' | 'owner';

export type ViewReason =
    | 'unauthenticated'   // not logged in
    | 'wrong-assignee'    // logged in, but another contributor holds the claim
    | 'not-claimable'     // logged in, row is in a non-claim state (e.g. awaiting_alignment)
    | 'released'          // post-publish, awaiting timestamp generation
    | 'marked_ready'      // user marked-ready their own claim and the row is frozen
    | 'completed'         // reciter is in published terminal state
    | 'discarded';        // reciter is admin-soft-deleted

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

/** Replace the whole mode in one call. */
export function setEditingMode(mode: EditingMode): void {
    editingMode.set(mode);
}

/**
 * Map `(currentUser, reciterTask)` → `EditingMode`. The function is pure
 * so it can be unit-tested in isolation; callers (typically the segments
 * tab on reciter/task updates) call `setEditingMode(syncEditingMode(...))`.
 *
 * Branches (first match wins):
 *   1. user == null  → view / unauthenticated
 *   2. task == null  → view / unauthenticated (route still loading)
 *   3. row.visibility == discarded → view / discarded
 *   4. user.role == owner && marked_ready → view / marked_ready
 *   5. user.role == owner → owner  (any state, no claim required)
 *   6. row.state == completed → view / completed
 *   7. row.state == released → view / released
 *   8. row.state == under_review && marked_ready && user is assignee → view / marked_ready
 *   9. row.state == under_review && user is assignee → editor
 *   10. maintainer && row.state == under_review && !marked_ready → maintainer
 *   11. row.state in {catalogued, awaiting_alignment, awaiting_timestamps} → view / not-claimable
 *   12. else → view / wrong-assignee
 */
export function syncEditingMode(
    user: CurrentUser | null,
    task: ReciterTask | null,
): EditingMode {
    if (user === null || user.hf_user_id === null) {
        return { kind: 'view', viewReason: 'unauthenticated' };
    }
    if (task === null) {
        return { kind: 'view', viewReason: 'unauthenticated' };
    }
    const row = task.row;
    const isAssignee = row.assignee_hf_id === user.hf_user_id;

    if (row.visibility === 'discarded') {
        return { kind: 'view', viewReason: 'discarded' };
    }
    // Owner fast-path: can edit any public, non-frozen reciter regardless of state.
    if (user.role === 'owner') {
        if (row.marked_ready) return { kind: 'view', viewReason: 'marked_ready' };
        return { kind: 'owner' };
    }
    if (row.state === 'completed') {
        return { kind: 'view', viewReason: 'completed' };
    }
    if (row.state === 'released') {
        return { kind: 'view', viewReason: 'released' };
    }
    if (row.state === 'under_review') {
        if (row.marked_ready && isAssignee) {
            return { kind: 'view', viewReason: 'marked_ready' };
        }
        if (!row.marked_ready && isAssignee) {
            return { kind: 'editor' };
        }
        if (!row.marked_ready && user.role === 'maintainer') {
            return { kind: 'maintainer' };
        }
        return { kind: 'view', viewReason: 'wrong-assignee' };
    }
    // catalogued / awaiting_alignment / awaiting_timestamps — not claimable
    // (or in transit). Use a distinct reason so the popover copy doesn't
    // accidentally claim someone else is reviewing it.
    return { kind: 'view', viewReason: 'not-claimable' };
}

/** Convenience: read current mode synchronously. */
export function currentMode(): EditingMode {
    return get(editingMode);
}
