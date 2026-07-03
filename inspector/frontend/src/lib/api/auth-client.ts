/**
 * Auth client: sign-in / sign-out helpers.
 *
 * `signIn` (standalone tab) navigates the browser to
 * `/api/auth/login?return=<path>`; the backend redirects to HF for consent and
 * back to `/api/auth/callback` which sets the identity cookie and redirects
 * again to `?return`. Inside the cross-site HF iframe that redirect can't work
 * (X-Frame-Options + third-party cookie), so `signIn` delegates to the
 * popup + Storage Access flow in `embedded-auth.ts` and surfaces its phases via
 * the sign-in modal.
 *
 * `signOut` POSTs `/api/auth/logout` then resets the local `currentUser`
 * store. Active claims are NOT released by signing out — that's a
 * deliberate separation; release is its own action.
 */

import { resetCurrentUser } from '../stores/current-user';
import { openSignInModal } from '../stores/sign-in-modal';
import { beginEmbeddedSignIn, isEmbedded } from './embedded-auth';

export function signIn(returnPath?: string | null): void {
    if (typeof window === 'undefined') return;
    const target = returnPath ?? window.location.pathname + window.location.search;
    if (isEmbedded()) {
        // Open the popup synchronously within this click gesture (popup-blocker
        // safe), then surface the flow's phases in the modal.
        beginEmbeddedSignIn(target);
        openSignInModal(target);
        return;
    }
    window.location.assign(`/api/auth/login?return=${encodeURIComponent(target)}`);
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
