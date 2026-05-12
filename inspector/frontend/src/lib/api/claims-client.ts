/**
 * Claim flow client. Wraps the four POST endpoints and translates the
 * backend's status code envelope into UI side effects:
 *
 *   - 200 → resolves with the new row.
 *   - 401 → toast "Sign in to claim" + open SignInModal; rejects.
 *   - 403 → toast with the error body; rejects.
 *   - 409 → toast "Release {other} first" (or generic conflict); rejects.
 *   - other → generic error toast; rejects.
 *
 * Callers can ``await`` and react on success; failure cases have already
 * surfaced UX (toast/modal) so the caller usually doesn't need to do more.
 */

import { loadCurrentUser } from '../stores/current-user';
import { openSignInModal } from '../stores/sign-in-modal';
import { pushToast } from '../stores/toast';
import { fetchJson } from './index';
import type { ReciterRow } from './reciter-task';

type RouteName = 'claim' | 'release' | 'mark-ready' | 'unmark-ready';

interface ErrorBody {
    error?: string;
    existing_claim?: string;
}

async function _post(route: RouteName, slug: string): Promise<ReciterRow> {
    const res = await fetch(`/api/${route}/${encodeURIComponent(slug)}`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
    });
    if (res.ok) {
        const row = (await res.json()) as ReciterRow;
        // The active_claim field in /api/me derives from state — refresh
        // the local store so the rest of the UI sees the right value.
        void loadCurrentUser();
        return row;
    }
    let body: ErrorBody = {};
    try {
        body = (await res.json()) as ErrorBody;
    } catch {
        /* swallow */
    }

    if (res.status === 401) {
        pushToast({ kind: 'info', text: 'Sign in with Hugging Face to continue.' });
        openSignInModal();
    } else if (res.status === 409 && body.existing_claim) {
        pushToast({
            kind: 'warn',
            text: `Release ${body.existing_claim} first to claim ${slug}.`,
            ttl: 6000,
        });
    } else {
        pushToast({
            kind: 'error',
            text: body.error || `Request failed (${res.status}).`,
            ttl: 5000,
        });
    }
    throw new Error(body.error || `${route} failed: ${res.status}`);
}

export const claim = (slug: string) => _post('claim', slug);
export const release = (slug: string) => _post('release', slug);
export const markReady = (slug: string) => _post('mark-ready', slug);
export const unmarkReady = (slug: string) => _post('unmark-ready', slug);
