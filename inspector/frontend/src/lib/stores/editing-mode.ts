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
    | 'claimable'         // logged in, row is free to claim (awaiting_review)
    | 'holds-other-claim' // free to claim, but the user already holds another active claim
    | 'wrong-assignee'    // logged in, but another contributor holds the claim
    | 'not-available'     // pre-review: catalogued / awaiting_alignment (not editable yet)
    | 'published'         // post-publish: released (read-only)
    | 'marked_ready'      // user marked-ready their own claim and the row is frozen
    | 'guides_unread'     // would-be editor who hasn't read the onboarding guides yet
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
 * Gate ORDER (deliberate — the user should learn WHY they can't edit before
 * being asked to read guides):
 *   1. Not signed in            → view / unauthenticated   (→ sign-in modal)
 *   2. State / ownership denial → view / <specific reason> (→ popover)
 *   3. Onboarding guides unread → view / guides_unread     (→ guides gate)
 *   4. Otherwise                → editable kind (editor | maintainer | owner)
 *
 * The guide gate is applied LAST, only once the user is confirmed to be in a
 * genuinely editable position — so "sign in" and "you can't edit this because
 * <state>" always win over "read the guides first". A contributor with a fresh
 * claim is exactly who should hit the guide gate; nobody else reaches it.
 *
 * Denial reasons map 1:1 to the real lifecycle situation (no internal tokens
 * leak to copy):
 *   - discarded                              → discarded
 *   - awaiting_review (free to claim)        → claimable
 *   - under_review, someone else's claim     → wrong-assignee
 *   - under_review, marked-ready, yours      → marked_ready (frozen)
 *   - catalogued / awaiting_alignment        → not-available (pre-review)
 *   - released                               → published (read-only)
 *
 * Owner override is total: an owner edits any public reciter regardless of
 * state, claim, or marked_ready freeze — but still reads the guides once.
 *
 * `allGuidesRead` defaults to `true` so callers/tests that don't pass it are
 * never gated — only the segments tab threads the real per-user value
 * (`allGuidesRead($currentUser.guides_read)`). No dev-mode exemption: the gate
 * must be visible/testable locally, and dev is never prod.
 */
export function syncEditingMode(
    user: CurrentUser | null,
    task: ReciterTask | null,
    allGuidesRead: boolean = true,
): EditingMode {
    // 1. Sign-in always wins.
    if (user === null || user.hf_user_id === null) {
        return { kind: 'view', viewReason: 'unauthenticated' };
    }
    if (task === null) {
        // Route still loading — treat as not-yet-signed-in (no affordance).
        return { kind: 'view', viewReason: 'unauthenticated' };
    }

    // 2. Resolve the editable kind (or a specific denial reason). The guide
    //    gate is deliberately NOT applied here — see step 3.
    const denialOrKind = _resolveEditAccess(user, task);
    if (denialOrKind.kind === 'view') {
        return denialOrKind; // state / ownership denial — beats the guide gate
    }

    // 3. Onboarding guides are the LAST gate — only a confirmed editor reaches it.
    if (!allGuidesRead) {
        return { kind: 'view', viewReason: 'guides_unread' };
    }

    // 4. Cleared every gate.
    return denialOrKind;
}

/**
 * Pure access resolver: returns the editable `kind` the user is entitled to,
 * or a `view` mode carrying the specific denial reason. Does NOT consider the
 * onboarding guide gate (the caller applies that last so denials surface first).
 */
function _resolveEditAccess(user: CurrentUser, task: ReciterTask): EditingMode {
    const row = task.row;
    const isAssignee = row.assignee_hf_id === user.hf_user_id;

    // Visibility trumps everything, including owner override.
    if (row.visibility === 'discarded') {
        return { kind: 'view', viewReason: 'discarded' };
    }

    // Owner override is total — any public reciter, any state, ignores the
    // marked_ready freeze.
    if (user.role === 'owner') {
        return { kind: 'owner' };
    }

    switch (row.state) {
        case 'awaiting_review':
            // Free to claim — nobody is reviewing it yet. But a non-owner can
            // only hold one claim at a time: if they already hold a different
            // one, surface THAT (precedence over "claim it") so the popover
            // doesn't dangle a button that the confirm modal would only reject.
            if (
                user.active_claim !== null &&
                user.active_claim !== row.slug
            ) {
                return { kind: 'view', viewReason: 'holds-other-claim' };
            }
            return { kind: 'view', viewReason: 'claimable' };

        case 'under_review':
            if (isAssignee) {
                // The reviewer's own marked-ready row is frozen until they
                // choose "Continue editing".
                return row.marked_ready
                    ? { kind: 'view', viewReason: 'marked_ready' }
                    : { kind: 'editor' };
            }
            // A maintainer may edit any unmarked under_review row; once it's
            // marked_ready it's frozen for them too (publish/send-back only).
            if (user.role === 'maintainer' && !row.marked_ready) {
                return { kind: 'maintainer' };
            }
            return { kind: 'view', viewReason: 'wrong-assignee' };

        case 'catalogued':
        case 'awaiting_alignment':
            // Pre-review: the recitation isn't ready for editing yet.
            return { kind: 'view', viewReason: 'not-available' };

        case 'released':
            // Post-publish: read-only (timestamps generated, reciter live).
            return { kind: 'view', viewReason: 'published' };

        default:
            return { kind: 'view', viewReason: 'not-available' };
    }
}

/** Convenience: read current mode synchronously. */
export function currentMode(): EditingMode {
    return get(editingMode);
}
