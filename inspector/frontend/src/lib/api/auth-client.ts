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
    const target = returnPath ?? (typeof window !== 'undefined'
        ? window.location.pathname + window.location.search
        : '/');
    const url = `/api/auth/login?return=${encodeURIComponent(target)}`;
    if (typeof window !== 'undefined') {
        window.location.assign(url);
    }
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
