/**
 * Auth client: sign-in / sign-out helpers.
 *
 * `signIn` navigates the browser to `/api/auth/login?return=<path>`; the
 * backend redirects to HF for consent and back to `/api/auth/callback`
 * which sets the identity cookie and redirects again to `?return`.
 *
 * `signOut` POSTs `/api/auth/logout` then resets the local `currentUser`
 * store. Active claims are NOT released by signing out — that's a
 * deliberate separation; release is its own action.
 */

import { resetCurrentUser } from '../stores/current-user';

export function signIn(returnPath?: string | null): void {
    if (typeof window === 'undefined') return;
    const target = returnPath ?? window.location.pathname + window.location.search;
    const url = `/api/auth/login?return=${encodeURIComponent(target)}`;
    // Embedded in the huggingface.co iframe the OAuth round-trip is
    // third-party, so the Flask session cookie carrying the OAuth state is
    // blocked (Safari ITP rejects it outright despite SameSite=None;Secure),
    // and Authlib raises MismatchingStateError on the callback. Break the
    // whole tab out to the first-party *.hf.space origin so authorize→callback
    // runs top-level and the state cookie survives. Mirrors the QF login
    // break-out in BookmarksPanel.svelte.
    if (window.self !== window.top) {
        window.open(`${window.location.origin}${url}`, '_top');
        return;
    }
    window.location.assign(url);
}

export async function signOut(): Promise<void> {
    try {
        await fetch('/api/auth/logout', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
        });
    } finally {
        resetCurrentUser();
    }
}
