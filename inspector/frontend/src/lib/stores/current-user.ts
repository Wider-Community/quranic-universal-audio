/**
 * Current-user identity store.
 *
 * Loaded on app boot from `/api/me`. Replaced after sign-in/sign-out and
 * after any state-mutating claim action that touches `active_claim`.
 *
 * Shape is stable for anonymous (all fields null) so consumers can read
 * the same schema regardless of auth state.
 */

import { derived, writable } from 'svelte/store';

import { fetchJson } from '../api';

export type Role = 'contributor' | 'maintainer' | 'owner' | null;

export interface CurrentUser {
    login: string | null;
    hf_user_id: string | null;
    role: Role;
    active_claim: string | null;
    /**
     * True when the backend is running with the dev-mode auth bypass
     * (`INSPECTOR_DEV_MODE=1`). Only ever true locally — never on the
     * deployed HF Space. Toggles the in-app role switcher UI.
     */
    dev_mode: boolean;
}

const _ANON: CurrentUser = {
    login: null,
    hf_user_id: null,
    role: null,
    active_claim: null,
    dev_mode: false,
};

export const currentUser = writable<CurrentUser>(_ANON);

/** True iff the user is signed in (has a verified HF identity). */
export function isSignedIn(u: CurrentUser): boolean {
    return u.hf_user_id !== null;
}

/**
 * Global role-tier derived stores driven by ``currentUser`` (not the
 * reciter-scoped ``editingMode`` store in ``editing-mode.ts``). These are
 * the right hooks for dashboard-level UI gating: admin notification rail,
 * owner-only delete affordances, etc.
 *
 * - ``isAdmin`` — maintainer OR owner. Mirrors ``services/permissions.is_maintainer``.
 * - ``isOwner`` — owner only. Mirrors ``services/permissions.is_owner``.
 */
export const isAdmin = derived(
    currentUser,
    (u) => u.role === 'maintainer' || u.role === 'owner',
);

export const isOwner = derived(currentUser, (u) => u.role === 'owner');

/** Fetch /api/me and replace the store. Returns the loaded value. */
export async function loadCurrentUser(): Promise<CurrentUser> {
    try {
        const me = await fetchJson<CurrentUser>('/api/me');
        currentUser.set(me ?? _ANON);
        return me ?? _ANON;
    } catch {
        currentUser.set(_ANON);
        return _ANON;
    }
}

/** Force the store back to anonymous. Use after explicit logout. */
export function resetCurrentUser(): void {
    currentUser.set(_ANON);
}
