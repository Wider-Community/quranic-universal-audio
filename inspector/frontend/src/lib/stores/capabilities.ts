/**
 * Capability-aware UI gating.
 *
 * The backend resolves the caller's capability set fresh per request and ships
 * it on `/api/me` (`currentUser.capabilities`). These helpers gate UI on
 * capability membership instead of a hardcoded role tier, so an owner's toggle
 * in the Permissions tab reflects in the UI on the affected user's next
 * `/api/me` load — no role check to keep in sync.
 *
 * Two flavours:
 * - `can(id)` — a reactive `Readable<boolean>` for `{#if $can('x')}` gating.
 * - `hasCapability(user, id)` — a pure imperative check for unit-testable
 *   functions that already receive the user (e.g. `syncEditingMode`).
 *
 * Capability ids MUST match the backend registry
 * (`scripts/lib/schemas/capabilities.py`) — confirm against the live
 * `GET /api/admin/permissions` response rather than inventing ids.
 */

import { derived, type Readable } from 'svelte/store';

import { type CurrentUser,currentUser } from './current-user';

const capSet = derived(currentUser, (u) => new Set(u.capabilities ?? []));

/** Reactive predicate store for one capability id. */
export function can(capabilityId: string): Readable<boolean> {
    return derived(capSet, (s) => s.has(capabilityId));
}

/** Imperative one-shot check off a `CurrentUser` (for pure functions). */
export function hasCapability(
    user: Pick<CurrentUser, 'capabilities'> | null | undefined,
    capabilityId: string,
): boolean {
    return !!user && (user.capabilities ?? []).includes(capabilityId);
}
