/**
 * Sign-in modal open/close state.
 *
 * The modal is a single root-mounted component (see `App.svelte`) opened
 * imperatively from anywhere — typically when an anonymous user clicks
 * "Claim" and we need to nudge them through HF OAuth.
 */

import { writable } from 'svelte/store';

interface SignInModalState {
    open: boolean;
    /** Path to redirect back to after callback. Defaults to current pathname+search. */
    returnPath: string | null;
    /** Action-specific title + body. Falls back to generic copy when null. */
    context: { title: string; body: string } | null;
}

export const signInModal = writable<SignInModalState>({
    open: false,
    returnPath: null,
    context: null,
});

export function openSignInModal(
    returnPath?: string | null,
    context?: { title: string; body: string } | null,
): void {
    signInModal.set({
        open: true,
        returnPath: returnPath ?? (typeof window !== 'undefined'
            ? window.location.pathname + window.location.search
            : null),
        context: context ?? null,
    });
}

export function closeSignInModal(): void {
    signInModal.update((s) => ({ ...s, open: false }));
}
