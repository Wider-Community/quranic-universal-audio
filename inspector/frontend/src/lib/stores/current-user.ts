/**
 * Current-user identity store.
 *
 * Loaded on app boot from `/api/me`. Replaced after sign-in/sign-out and
 * after any state-mutating claim action that touches `active_claim`.
 *
 * Shape is stable for anonymous (all fields null) so consumers can read
 * the same schema regardless of auth state.
 */

import { writable } from 'svelte/store';

import { fetchJson } from '../api';

export type Role = 'contributor' | 'maintainer' | 'owner' | null;

export interface CurrentUser {
    login: string | null;
    hf_user_id: string | null;
    role: Role;
    active_claim: string | null;
}

const _ANON: CurrentUser = {
    login: null,
    hf_user_id: null,
    role: null,
    active_claim: null,
};

export const currentUser = writable<CurrentUser>(_ANON);

/** True iff the user is signed in (has a verified HF identity). */
export function isSignedIn(u: CurrentUser): boolean {
    return u.hf_user_id !== null;
}

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
