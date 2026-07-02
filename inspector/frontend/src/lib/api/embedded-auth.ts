/**
 * Embedded (HF-iframe) sign-in flow.
 *
 * When the app runs inside the cross-site `huggingface.co` iframe, the plain
 * redirect sign-in (`auth-client.signIn` → `window.location.assign`) breaks two
 * ways:
 *   1. HF's `/login` + `/oauth/authorize` send `X-Frame-Options: SAMEORIGIN`, so
 *      navigating the iframe to them renders nothing in Firefox/Safari (they
 *      check every ancestor; the immediate parent `*.hf.space` ≠ HF).
 *   2. The identity cookie is third-party in the iframe, so even a completed
 *      login isn't sent on later requests under 3p-cookie blocking.
 *
 * The iframe sandbox forbids top navigation but allows popups and the Storage
 * Access API, so this module:
 *   - opens the sign-in in a popup (top-level, first-party HF → renders + sets
 *     the cookie first-party on the popup's `*.hf.space` origin),
 *   - then requests storage access so the iframe's own same-origin `/api/me`
 *     carries the now-unpartitioned cookie.
 *
 * If storage access is denied or the popup is blocked, the caller surfaces a
 * "open in its own tab" fallback (fully first-party). Drives `SignInModal`.
 */

import { writable } from 'svelte/store';

import { loadCurrentUser } from '../stores/current-user';

/**
 * - `idle`         — no flow in progress (modal shows the CTA).
 * - `awaiting`     — popup open; waiting for the user to finish sign-in there.
 * - `finishing`    — popup done; resolving identity (+ storage access).
 * - `needs-continue` — signed in in the popup but the iframe still can't read the
 *                    cookie; needs one more click to request storage access with
 *                    a fresh user gesture.
 * - `done`         — signed in and the iframe can see it.
 * - `fallback`     — couldn't complete embedded; offer the own-tab escape hatch.
 */
export type EmbeddedAuthPhase =
    | 'idle'
    | 'awaiting'
    | 'finishing'
    | 'needs-continue'
    | 'done'
    | 'fallback';

interface EmbeddedAuthState {
    phase: EmbeddedAuthPhase;
}

export const embeddedAuth = writable<EmbeddedAuthState>({ phase: 'idle' });

/** True when the app is running inside another document's frame. A cross-origin
 *  parent makes `window.top` access throw — that itself means we're embedded. */
export function isEmbedded(): boolean {
    try {
        return window.self !== window.top;
    } catch {
        return true;
    }
}

/** First-party URL of this Space in its own tab — the guaranteed fallback. */
export function standaloneUrl(returnPath: string): string {
    const path = returnPath && returnPath.startsWith('/') ? returnPath : '/';
    return window.location.origin + path;
}

let _popup: Window | null = null;
let _cleanup: (() => void) | null = null;

function _setPhase(phase: EmbeddedAuthPhase): void {
    embeddedAuth.set({ phase });
}

/** Best-effort Storage Access API grant. Resolves true only if access is held. */
async function _tryRequestStorageAccess(): Promise<boolean> {
    try {
        if (typeof document.requestStorageAccess !== 'function') return false;
        await document.requestStorageAccess();
        return true;
    } catch {
        return false;
    }
}

/**
 * Open the sign-in popup. MUST be called synchronously from a user gesture
 * (click) or the browser's popup blocker kills it. Sets phase to `awaiting`,
 * or `fallback` if the popup couldn't open.
 */
export function beginEmbeddedSignIn(returnPath: string): void {
    _teardown();
    const url = `/api/auth/login?popup=1&return=${encodeURIComponent(returnPath)}`;
    _popup = window.open(url, 'hf_login', 'width=520,height=720,menubar=no,toolbar=no');
    if (!_popup) {
        _setPhase('fallback');
        return;
    }
    _setPhase('awaiting');
    // Returning users (prior first-party interaction with this origin) get the
    // grant on this gesture; the cookie the popup sets is then already readable.
    // New users are handled by the `needs-continue` step below.
    void _tryRequestStorageAccess();
    _watchPopup();
}

/** Listen for the popup's success postMessage; also poll for it being closed. */
function _watchPopup(): void {
    const onMessage = (e: MessageEvent): void => {
        if (e.origin !== window.location.origin) return;
        if (e.data && e.data.source === 'inspector-auth' && e.data.ok) {
            void _finish();
        }
    };
    window.addEventListener('message', onMessage);
    const poll = window.setInterval(() => {
        if (_popup && _popup.closed) void _finish();
    }, 700);
    _cleanup = () => {
        window.removeEventListener('message', onMessage);
        window.clearInterval(poll);
    };
}

function _delay(ms: number): Promise<void> {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/** Popup finished: resolve identity. If the iframe still can't see the session,
 *  ask for one more click to grant storage access with a fresh gesture. */
async function _finish(): Promise<void> {
    _teardown();
    _setPhase('finishing');
    // Where third-party cookies are allowed the popup's cookie is readable
    // straight away; a couple of short retries absorb the set-cookie/postMessage
    // race so those users skip the extra click. Browsers that block third-party
    // cookies never resolve here and fall through to the storage-access step.
    for (let attempt = 0; attempt < 3; attempt += 1) {
        const me = await loadCurrentUser();
        if (me.hf_user_id) {
            _setPhase('done');
            return;
        }
        if (attempt < 2) await _delay(500);
    }
    _setPhase('needs-continue');
}

/**
 * Finish sign-in from a fresh user gesture: request storage access, then
 * re-resolve identity. Falls back to the own-tab escape hatch if the iframe
 * still can't read the session.
 */
export async function continueWithStorageAccess(): Promise<void> {
    _setPhase('finishing');
    await _tryRequestStorageAccess();
    const me = await loadCurrentUser();
    _setPhase(me.hf_user_id ? 'done' : 'fallback');
}

function _teardown(): void {
    if (_cleanup) {
        _cleanup();
        _cleanup = null;
    }
}

/** Reset to idle and drop any popup/listener state (on modal close). */
export function resetEmbeddedAuth(): void {
    _teardown();
    _popup = null;
    _setPhase('idle');
}
